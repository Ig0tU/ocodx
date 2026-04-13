import sys
import os
import argparse
import subprocess
from multiprocessing import freeze_support

from prompt_toolkit import print_formatted_text, HTML
from prompt_toolkit.shortcuts import button_dialog, radiolist_dialog, message_dialog

from open_codex.agent_builder import AgentBuilder
from open_codex.interfaces.llm_agent import LLMAgent

# ANSI Colors for simple prints if needed
GREEN = "\033[92m"
RED = "\033[91m"
BLUE = "\033[94m"
RESET = "\033[0m"

def run_user_action(choice: str, command: str):
    if choice == "c":
        print_formatted_text(HTML("<green>Copying command to clipboard...</green>"))
        # Cross-platform copy using pyperclip (which is in dependencies)
        try:
            import pyperclip
            pyperclip.copy(command)
            print_formatted_text(HTML("<green>Command copied to clipboard!</green>"))
        except ImportError:
            # Fallback for macOS if pyperclip fails
            if sys.platform == "darwin":
                subprocess.run("pbcopy", universal_newlines=True, input=command)
                print_formatted_text(HTML("<green>Command copied to clipboard!</green>"))
            else:
                print_formatted_text(HTML("<red>Could not copy to clipboard. Please install 'pyperclip' or use a supported OS.</red>"))
    elif choice == "e":
        print_formatted_text(HTML("<green>Executing command...</green>"))
        subprocess.run(command, shell=True)
    else: 
        print_formatted_text(HTML("<red>Aborting...</red>"))
        sys.exit(0)  

def get_agent(args: argparse.Namespace) -> LLMAgent:
    model: str = args.model
    if args.ollama or args.ollama_cloud:
        host = args.ollama_host
        api_key = args.ollama_api_key or os.environ.get("OLLAMA_API_KEY")
        
        if args.ollama_cloud:
            host = "https://ollama.com/api"
            if not api_key:
                print_formatted_text(HTML("<red>Error: --ollama-cloud requires OLLAMA_API_KEY environment variable or --ollama-api-key flag.</red>"))
                sys.exit(1)
        
        print_formatted_text(HTML(f"<blue>Using {'Ollama Cloud' if args.ollama_cloud else 'Ollama'} with model: </blue><green>{model if model else 'Auto-detect'}</green>"))
        return AgentBuilder.get_ollama_agent(model=model, host=host, api_key=api_key)
    elif args.lmstudio:
        print_formatted_text(HTML(f"<blue>Using LM Studio with model: </blue><green>{model if model else 'Auto-detect'}</green>"))
        return AgentBuilder.get_lmstudio_agent(model=model, host=args.lmstudio_host)
    else:
        print_formatted_text(HTML("<blue>Using model: </blue><green>phi-4-mini-instruct</green>"))
        return AgentBuilder.get_phi_agent()

def get_help_message():
    return f"""
    Usage examples:
    open-codex list all files in current directory
    open-codex --ollama find all python files modified in the last week
    open-codex --lmstudio "create a tarball of the src directory"
    open-codex --ollama-cloud --model qwen3-coder:480b-cloud "analyze my docker network"
    """

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Open Codex: AI-powered CLI for shell command generation.",
                                     formatter_class=argparse.RawTextHelpFormatter,
                                     epilog=get_help_message())

    parser.add_argument("prompt", nargs="*", 
                        help="Natural language prompt")
    parser.add_argument("--model", type=str, 
                        help="Model name to use", default=None)
    parser.add_argument("--ollama", action="store_true", 
                        help="Use Ollama for LLM inference")
    parser.add_argument("--ollama-host", type=str, default="http://localhost:11434", 
                        help="Ollama API host.")
    parser.add_argument("--ollama-cloud", action="store_true",
                        help="Use Ollama Cloud for high-power models")
    parser.add_argument("--ollama-api-key", type=str,
                        help="Ollama API Key (overrides OLLAMA_API_KEY env var)")
    parser.add_argument("--lmstudio", action="store_true", 
                        help="Use LM Studio for LLM inference")
    parser.add_argument("--lmstudio-host", type=str, default="http://localhost:1234", 
                        help="LM Studio API host.")
    parser.add_argument("--tui", action="store_true",
                        help="Launch in TUI mode")
    parser.add_argument("--cli", action="store_true",
                        help="Run in classic CLI one-shot mode (even if prompt is present)")
    parser.add_argument("--web", action="store_true",
                        help="Launch web UI (opens browser, default unless --cli is specified)")
    parser.add_argument("--port", type=int, default=8000,
                        help="Port for web UI server (default: 8000)")

    return parser.parse_args()

def select_ollama_cloud_model(api_key: str) -> str:
    # Top-tier code-powerhouse models
    top_models = [
        ("qwen3-coder:480b-cloud", "Qwen3 Coder 480B (Ultra)"),
        ("deepseek-v3.1:671b-cloud", "DeepSeek V3.1 671B (Ultra)"),
        ("qwen3.5:latest-cloud", "Qwen 3.5 (Balanced)"),
        ("ministral-3:latest-cloud", "Ministral 3 (Fast)"),
    ]
    
    model = radiolist_dialog(
        title="Ollama Cloud - Select Powerhouse Model",
        text="Choose a top-tier code-specialized model:",
        values=top_models
    ).run()
    
    if not model:
        sys.exit(0)
    return model

def select_lmstudio_model(host: str) -> str:
    try:
        agent = AgentBuilder.get_lmstudio_agent(model=None, host=host)
        models = agent._get_available_models()
        if not models:
            message_dialog(title="Error", text=f"No models found at {host}").run()
            sys.exit(1)
            
        model = radiolist_dialog(
            title="LM Studio - Select Model",
            text="Choose a model from your LM Studio instance:",
            values=[(m, m) for m in models]
        ).run()
        
        if not model:
            sys.exit(0)
        return model
    except Exception as e:
        message_dialog(title="Error", text=f"Could not connect to LM Studio: {e}").run()
        sys.exit(1)

def select_ollama_model(host: str) -> str:
    try:
        import ollama
        client = ollama.Client(host=host)
        models_data = client.list()
        models = [m.model for m in models_data.models]
        
        if not models:
            message_dialog(title="Error", text=f"No models found in Ollama at {host}").run()
            sys.exit(1)
            
        model = radiolist_dialog(
            title="Ollama - Select Model",
            text="Choose a model from your local Ollama instance:",
            values=[(m, m) for m in models]
        ).run()
        
        if not model:
            sys.exit(0)
        return model
    except Exception as e:
        message_dialog(title="Error", text=f"Could not connect to Ollama: {e}").run()
        sys.exit(1)

def run_one_shot(agent: LLMAgent, prompt: str) -> str:
    try:
        return agent.one_shot_mode(prompt)
    except Exception as e:
        print_formatted_text(HTML(f"<red>Error generating command: {e}</red>"))
        sys.exit(1)

def get_user_action_interactive(command: str) -> str:
    return button_dialog(
        title="Codex Suggestion",
        text=f"Generated Command:\n\n  $ {command}\n\nWhat would you like to do?",
        buttons=[
            ("Execute", "e"),
            ("Copy", "c"),
            ("Abort", "a"),
        ],
    ).run()

def launch_web(port: int = 8000, prompt: str = None):
    import threading
    import webbrowser
    import uvicorn
    from urllib.parse import quote
    from open_codex.api import app

    url = f"http://localhost:{port}"
    if prompt:
        url += f"/?prompt={quote(prompt)}"
        
    print_formatted_text(HTML(f"<blue>Starting Open Codex web UI at </blue><green>{url}</green>"))

    def _open():
        import time
        time.sleep(1.2)
        webbrowser.open(url)

    threading.Thread(target=_open, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def main():
    args = parse_args()

    # --tui: terminal UI
    if args.tui:
        from open_codex.tui import launch_tui
        launch_tui()
        return

    # default to web unless --cli is specified
    if not args.cli and (args.web or not args.prompt or args.prompt):
        prompt_str = " ".join(args.prompt).strip() if args.prompt else None
        launch_web(port=args.port, prompt=prompt_str)
        return

    # CLI one-shot mode (explicit --cli or fallback if prompt is present and cli specified)
    if args.cli and not args.prompt:
        print_formatted_text(HTML("<red>Error: --cli mode requires a prompt.</red>"))
        sys.exit(1)
    if args.lmstudio and not args.model:
        args.model = select_lmstudio_model(args.lmstudio_host)
    elif args.ollama_cloud and not args.model:
        api_key = args.ollama_api_key or os.environ.get("OLLAMA_API_KEY")
        args.model = select_ollama_cloud_model(api_key)
    elif args.ollama and not args.model:
        args.model = select_ollama_model(args.ollama_host)

    agent = get_agent(args)

    # join the prompt arguments into a single string
    prompt = " ".join(args.prompt).strip() 
    
    # Visual feedback - Codex vibe
    print_formatted_text(HTML(f"\n<blue><b>&gt;</b></blue> <white>Analyzing request:</white> <green>'{prompt}'</green>"))
    
    response = run_one_shot(agent, prompt)
    
    # Codex-style display
    print_formatted_text(HTML("\n<blue><b><u>Codex Suggestion</u></b></blue>"))
    print_formatted_text(HTML(f"<green>  $ {response}</green>\n"))
    
    action = get_user_action_interactive(response)
    if not action: # Dialog cancelled
        action = "a"
        
    run_user_action(action, response)

if __name__ == "__main__":
    freeze_support()
    main()
