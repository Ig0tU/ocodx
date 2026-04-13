import sys
import os
import subprocess
import threading
from typing import List, Optional

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.layout.containers import HSplit, VSplit, Window, WindowAlign, FloatContainer, Float
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.widgets import Frame, TextArea, RadioList, Label, Button
from prompt_toolkit.styles import Style
from prompt_toolkit.formatted_text import HTML

from open_codex.agent_builder import AgentBuilder
from open_codex.interfaces.llm_agent import LLMAgent
from open_codex.agents.lmstudio_agent import LMStudioAgent

class CodexTUI:
    def __init__(self, initial_agent_type="phi"):
        self.agent: Optional[LLMAgent] = None
        self.current_agent_type = initial_agent_type
        self.output_text = ""
        self.loading = False
        self.available_models = []
        
        # ASCII Header
        self.header_text = HTML(
            "<green><b>   ____  ____  ________   __  ______  ____  _______  __</b></green>\n"
            "<green><b>  / __ \\/ __ \\/ ____/ | / / / ____/ __ \\/ __ \\/ ____/ |/ /</b></green>\n"
            "<green><b> / / / / /_/ / __/ /  |/ / / /   / / / / / / / __/  |   / </b></green>\n"
            "<green><b>/ /_/ / ____/ /___/ /|  / / /___/ /_/ / /_/ / /___ /   |  </b></green>\n"
            "<green><b>\\____/_/   /_____/_/ |_/  \\____/\\____/_____/_____/_/|_|  </b></green>\n"
            "<blue>  --[ v0.1.18 ]--[ SYSTEM: ARCX-9 ]--[ BY ARCSILLC ]--</blue>"
        )
        
        # UI Elements
        self.model_radio = RadioList(values=[
            ("phi", "Local (Phi-4 Mini)"),
            ("lmstudio", "LM Studio"),
            ("ollama", "Ollama (Local)"),
            ("ollama_cloud", "Ollama Cloud")
        ])
        
        # Default host values
        self.lm_host = "http://localhost:1234"
        self.ollama_host = "http://localhost:11434"
        self.ollama_cloud_host = "https://ollama.com/api"
        
        # API Key field (only shown/used for Ollama Cloud)
        self.api_key_field = TextArea(
            text=os.environ.get("OLLAMA_API_KEY", ""),
            password=True,
            multiline=False,
            height=1
        )
        
        self.model_selector = RadioList(values=[("auto", "Auto-select best")])
        
        self.input_field = TextArea(
            height=3,
            multiline=True,
        )
        
        self.output_field = TextArea(
            text="",
            read_only=True,
            style="class:output-field"
        )
        
        self.status_label = Label(text="Ready")
        
        # Buttons
        self.generate_btn = Button(text="Generate", handler=self.generate_command)
        self.copy_btn = Button(text="Copy", handler=self.copy_command)
        self.execute_btn = Button(text="Execute", handler=self.execute_command)
        self.refresh_models_btn = Button(text="Refresh Models", handler=self.refresh_models)
        
        # Layout
        self.kb = KeyBindings()
        self.setup_keybindings()
        
        self.app = self.create_app()
        
        # Initial model refresh
        self.refresh_models()

    def setup_keybindings(self):
        @self.kb.add("c-c")
        @self.kb.add("q")
        def _(event):
            event.app.exit()

        @self.kb.add("c-j")
        def _(event):
            if self.input_field.window.content.buffer.text.strip():
                self.generate_command()

        @self.kb.add("c-x")
        def _(event):
            self.execute_command()

        @self.kb.add("c-y")
        def _(event):
            self.copy_command()

        @self.kb.add("tab")
        def _(event):
            event.app.layout.focus_next()

        @self.kb.add("s-tab")
        def _(event):
            event.app.layout.focus_previous()

    def refresh_models(self):
        source = self.model_radio.current_value
        self.status_label.text = f"Refreshing {source} models..."
        
        def _fetch():
            models = []
            try:
                if source == "lmstudio":
                    from open_codex.agents.lmstudio_agent import LMStudioAgent
                    agent = LMStudioAgent(system_prompt="", host=self.lm_host)
                    models = agent._get_available_models()
                elif source == "ollama":
                    import ollama
                    client = ollama.Client(host=self.ollama_host)
                    models = [m.model for m in client.list().models if m.model]
                elif source == "ollama_cloud":
                    # For cloud, we often show a curated list or fetch if possible
                    models = ["qwen3-coder:480b-cloud", "deepseek-v3.1:671b-cloud", "qwen3.5:latest-cloud", "ministral-3:latest-cloud"]
                
                if models:
                    self.model_selector.values = [("auto", "Auto-select best")] + [(m, m) for m in models]
                    self.model_selector.current_value = "auto"
                else:
                    self.model_selector.values = [("none", "No models found")]
                    self.model_selector.current_value = "none"
                
                self.status_label.text = "Models updated"
            except Exception as e:
                self.status_label.text = f"Error: {str(e)}"
            
            self.app.invalidate()
            
        threading.Thread(target=_fetch, daemon=True).start()

    def copy_command(self):
        cmd = self.output_field.text.strip()
        if cmd and cmd != "Infiltrating the mainframe..." and not cmd.startswith("Error:"):
            try:
                import pyperclip
                pyperclip.copy(cmd)
                self.status_label.text = "Copied to clipboard!"
            except:
                self.status_label.text = "Copy failed. Install pyperclip."

    def execute_command(self):
        cmd = self.output_field.text.strip()
        if cmd and cmd != "Infiltrating the mainframe..." and not cmd.startswith("Error:"):
            self.status_label.text = "Executing command..."
            def _run():
                try:
                    import subprocess
                    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                    output = f"Output:\n{result.stdout}\n{result.stderr}"
                    self.output_field.text = f"{cmd}\n\n---\n{output}"
                    self.status_label.text = "Execution completed"
                except Exception as e:
                    self.status_label.text = f"Execution failed: {str(e)}"
            threading.Thread(target=_run, daemon=True).start()

    def generate_command(self):
        if self.loading:
            return
            
        prompt = self.input_field.text.strip()
        if not prompt:
            return

        self.loading = True
        self.status_label.text = "Generating..."
        self.output_field.text = "Infiltrating the mainframe..."
        
        def _run():
            try:
                # Get selected agent
                agent_type = self.model_radio.current_value
                model_choice = self.model_selector.current_value
                if model_choice == "auto" or model_choice == "none":
                    model_choice = None
                
                if agent_type == "phi":
                    agent = AgentBuilder.get_phi_agent()
                elif agent_type == "lmstudio":
                    agent = AgentBuilder.get_lmstudio_agent(model=model_choice, host=self.lm_host)
                elif agent_type == "ollama":
                    agent = AgentBuilder.get_ollama_agent(model=model_choice or "llama3", host=self.ollama_host)
                elif agent_type == "ollama_cloud":
                    api_key = self.api_key_field.text.strip()
                    agent = AgentBuilder.get_ollama_agent(
                        model=model_choice or "qwen3-coder:480b-cloud", 
                        host=self.ollama_cloud_host,
                        api_key=api_key
                    )
                
                response = agent.one_shot_mode(prompt)
                self.output_field.text = response
                self.status_label.text = "Success"
            except Exception as e:
                self.output_field.text = f"Error: {str(e)}"
                self.status_label.text = "Failed"
            finally:
                self.loading = False
                self.app.invalidate()
        
        threading.Thread(target=_run, daemon=True).start()

    def create_app(self):
        sidebar = Frame(
            HSplit([
                Label(text="SOURCE", style="class:sidebar-header"),
                self.model_radio,
                Window(height=1),
                Label(text="API KEY (Cloud)", style="class:sidebar-header"),
                self.api_key_field,
                Window(height=1),
                Label(text="MODELS", style="class:sidebar-header"),
                self.model_selector,
                Window(height=1),
                self.refresh_models_btn,
                Window(),
            ]),
            width=30,
            style="class:sidebar"
        )
        
        main_content = HSplit([
            Window(content=FormattedTextControl(self.header_text), height=6, align=WindowAlign.CENTER),
            Frame(
                HSplit([
                    Label(text="PROMPT", style="class:label"),
                    self.input_field,
                    VSplit([
                        Window(),
                        self.generate_btn,
                    ])
                ]),
                style="class:input-frame"
            ),
            Frame(
                HSplit([
                    Label(text="CODEX OUTPUT", style="class:label"),
                    self.output_field,
                    VSplit([
                        Window(),
                        self.copy_btn,
                        Window(width=1),
                        self.execute_btn,
                    ])
                ]),
                style="class:output-frame"
            ),
            VSplit([
                self.status_label,
                Window(align=WindowAlign.RIGHT, content=FormattedTextControl(
                    HTML("<gray>Ctrl+J: Gen | Ctrl+Y: Copy | Ctrl+X: Run | Tab: Cycle | q: Quit</gray>")
                ))
            ], style="class:status-bar")
        ])
        
        root_container = VSplit([
            sidebar,
            main_content
        ])
        
        style = Style.from_dict({
            "sidebar": "bg:#000000 #00ff41",
            "sidebar-header": "bold #00ff41 underline",
            "input-frame": "bg:#0a0a0a #00ff41",
            "output-frame": "bg:#050505 #00ff41",
            "output-field": "#00ff41 bold",
            "label": "bold #00ff41",
            "status-bar": "bg:#000000 #0080ff",
            "button": "bg:#00ff41 #000000",
            "button.focused": "bg:#ffffff #000000",
            "gray": "#888888",
        })
        
        return Application(
            layout=Layout(root_container, focused_element=self.input_field),
            key_bindings=self.kb,
            style=style,
            full_screen=True,
            mouse_support=True,
        )

    def run(self):
        self.app.run()

def launch_tui():
    tui = CodexTUI()
    tui.run()
