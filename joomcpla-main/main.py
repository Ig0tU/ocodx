import os
import httpx
import json
import re
from mcp.server.fastmcp import FastMCP
import markdown
import bleach
import google.generativeai as genai
from huggingface_hub import InferenceClient
from transformers import pipeline
import asyncio
from typing import Optional, List, Dict, Any


mcp = FastMCP("Joomla Articles MCP")

JOOMLA_BASE_URL = os.getenv("JOOMLA_BASE_URL").rstrip("/")
BEARER_TOKEN = os.getenv("BEARER_TOKEN")

# AI Service Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
HUGGINGFACE_API_TOKEN = os.getenv("HUGGINGFACE_API_TOKEN")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

JOOMLA_ARTICLES_API_URL = f"{JOOMLA_BASE_URL}/api/index.php/v1/content/articles"
JOOMLA_CATEGORIES_API_URL = f"{JOOMLA_BASE_URL}/api/index.php/v1/content/categories"

# Initialize AI services
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

if HUGGINGFACE_API_TOKEN:
    hf_client = InferenceClient(token=HUGGINGFACE_API_TOKEN)
else:
    hf_client = None

# Initialize local transformers pipelines (fallback when no API token)
try:
    summarizer = pipeline("summarization", model="facebook/bart-large-cnn")
    sentiment_analyzer = pipeline("sentiment-analysis")
    text_classifier = pipeline("zero-shot-classification")
except Exception as e:
    print(f"Warning: Could not initialize local transformers pipelines: {e}")
    summarizer = None
    sentiment_analyzer = None
    text_classifier = None


def generate_alias(title: str) -> str:
    """Convert a title to a slug alias (lowercase, hyphens, no special chars)."""
    alias = re.sub(r"[^a-z0-9\s-]", "", title.lower())
    alias = re.sub(r"\s+", "-", alias).strip("-")
    return alias


def convert_text_to_html(text: str) -> str:
    """
    Convert plain text to sanitized HTML using markdown and bleach.

    Args:
        text (str): The plain text to convert.

    Returns:
        str: Sanitized HTML content with allowed tags only.
    """
    html = markdown.markdown(text)
    allowed_tags = [
        "p",
        "br",
        "strong",
        "em",
        "ul",
        "ol",
        "li",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
    ]
    allowed_attributes = {}
    sanitized_html = bleach.clean(
        html, tags=allowed_tags, attributes=allowed_attributes, strip=True
    )
    return sanitized_html


# Gemini AI Helper Functions
async def generate_with_gemini(prompt: str, max_tokens: int = 1000) -> str:
    """Generate content using Gemini AI."""
    if not GEMINI_API_KEY:
        return "Error: Gemini API key not configured. Please set GEMINI_API_KEY environment variable."
    
    try:
        model = genai.GenerativeModel(GEMINI_MODEL)
        response = await asyncio.to_thread(
            model.generate_content,
            prompt,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=max_tokens,
                temperature=0.7,
            )
        )
        return response.text
    except Exception as e:
        return f"Error generating content with Gemini: {str(e)}"


# Hugging Face Helper Functions
async def generate_with_huggingface(prompt: str, model: str = "microsoft/DialoGPT-medium", max_tokens: int = 500) -> str:
    """Generate content using Hugging Face models."""
    if not hf_client:
        return "Error: Hugging Face API token not configured. Please set HUGGINGFACE_API_TOKEN environment variable."
    
    try:
        response = await asyncio.to_thread(
            hf_client.text_generation,
            prompt,
            model=model,
            max_new_tokens=max_tokens,
            temperature=0.7,
            return_full_text=False
        )
        return response
    except Exception as e:
        return f"Error generating content with Hugging Face: {str(e)}"


async def summarize_text_hf(text: str, max_length: int = 150) -> str:
    """Summarize text using Hugging Face models."""
    if hf_client:
        try:
            response = await asyncio.to_thread(
                hf_client.summarization,
                text,
                max_length=max_length,
                min_length=30
            )
            return response['summary_text']
        except Exception as e:
            return f"Error summarizing with Hugging Face API: {str(e)}"
    
    # Fallback to local model
    if summarizer:
        try:
            result = await asyncio.to_thread(
                summarizer,
                text,
                max_length=max_length,
                min_length=30,
                do_sample=False
            )
            return result[0]['summary_text']
        except Exception as e:
            return f"Error summarizing with local model: {str(e)}"
    
    return "Error: No summarization service available."


async def analyze_sentiment_hf(text: str) -> str:
    """Analyze sentiment using Hugging Face models."""
    if hf_client:
        try:
            response = await asyncio.to_thread(
                hf_client.text_classification,
                text,
                model="cardiffnlp/twitter-roberta-base-sentiment-latest"
            )
            return f"Sentiment: {response[0]['label']} (confidence: {response[0]['score']:.2f})"
        except Exception as e:
            return f"Error analyzing sentiment with Hugging Face API: {str(e)}"
    
    # Fallback to local model
    if sentiment_analyzer:
        try:
            result = await asyncio.to_thread(sentiment_analyzer, text)
            return f"Sentiment: {result[0]['label']} (confidence: {result[0]['score']:.2f})"
        except Exception as e:
            return f"Error analyzing sentiment with local model: {str(e)}"
    
    return "Error: No sentiment analysis service available."


# Gemini AI Tools
@mcp.tool(description="Generate article content using Google Gemini AI.")
async def generate_article_with_gemini(
    topic: str,
    style: str = "informative",
    length: str = "medium",
    target_audience: str = "general",
    include_title: bool = True
) -> str:
    """
    Generate article content using Google Gemini AI.
    
    Args:
        topic (str): The topic or subject for the article
        style (str): Writing style (informative, persuasive, casual, formal, technical)
        length (str): Article length (short, medium, long)
        target_audience (str): Target audience (general, technical, beginner, expert)
        include_title (bool): Whether to include a title in the generated content
    
    Returns:
        str: Generated article content
    """
    if not GEMINI_API_KEY:
        return "Error: Gemini API key not configured. Please set GEMINI_API_KEY environment variable."
    
    length_tokens = {"short": 300, "medium": 800, "long": 1500}
    max_tokens = length_tokens.get(length, 800)
    
    title_instruction = "Include a compelling title at the beginning." if include_title else "Do not include a title."
    
    prompt = f"""Write a {style} article about "{topic}" for a {target_audience} audience. 
    The article should be {length} in length. {title_instruction}
    
    Make the content engaging, well-structured, and informative. Use proper formatting with headings and paragraphs.
    Ensure the content is original and suitable for publication on a website.
    
    Topic: {topic}
    Style: {style}
    Target Audience: {target_audience}
    Length: {length}"""
    
    return await generate_with_gemini(prompt, max_tokens)


@mcp.tool(description="Enhance existing article content using Google Gemini AI.")
async def enhance_article_with_gemini(
    content: str,
    enhancement_type: str = "improve_readability",
    target_audience: str = "general"
) -> str:
    """
    Enhance existing article content using Google Gemini AI.
    
    Args:
        content (str): The existing article content to enhance
        enhancement_type (str): Type of enhancement (improve_readability, add_details, make_engaging, fix_grammar, optimize_seo)
        target_audience (str): Target audience for the enhancement
    
    Returns:
        str: Enhanced article content
    """
    if not GEMINI_API_KEY:
        return "Error: Gemini API key not configured. Please set GEMINI_API_KEY environment variable."
    
    enhancement_prompts = {
        "improve_readability": "Improve the readability and flow of this content while maintaining its core message.",
        "add_details": "Add more details, examples, and depth to this content to make it more comprehensive.",
        "make_engaging": "Make this content more engaging and compelling while keeping the same information.",
        "fix_grammar": "Fix any grammar, spelling, and punctuation errors in this content.",
        "optimize_seo": "Optimize this content for SEO by improving structure, adding relevant keywords naturally, and enhancing readability."
    }
    
    enhancement_instruction = enhancement_prompts.get(enhancement_type, enhancement_prompts["improve_readability"])
    
    prompt = f"""{enhancement_instruction}
    
    Target audience: {target_audience}
    
    Original content:
    {content}
    
    Please provide the enhanced version:"""
    
    return await generate_with_gemini(prompt, 1200)


@mcp.tool(description="Generate article title and meta description using Google Gemini AI.")
async def generate_title_meta_with_gemini(
    content: str,
    focus_keyword: str = None,
    title_style: str = "engaging"
) -> str:
    """
    Generate article title and meta description using Google Gemini AI.
    
    Args:
        content (str): The article content to analyze
        focus_keyword (str): Optional focus keyword to include
        title_style (str): Style for the title (engaging, professional, clickbait, descriptive)
    
    Returns:
        str: Generated title and meta description
    """
    if not GEMINI_API_KEY:
        return "Error: Gemini API key not configured. Please set GEMINI_API_KEY environment variable."
    
    keyword_instruction = f"Include the keyword '{focus_keyword}' naturally in both title and description." if focus_keyword else ""
    
    prompt = f"""Based on the following article content, generate:
    1. A {title_style} title (under 60 characters)
    2. A compelling meta description (under 160 characters)
    
    {keyword_instruction}
    
    Article content:
    {content[:1000]}...
    
    Format your response as:
    Title: [generated title]
    Meta Description: [generated meta description]"""
    
    return await generate_with_gemini(prompt, 300)


@mcp.tool(description="Retrieve all articles from the Joomla website.")
async def get_joomla_articles() -> str:
    """Retrieve all articles from the Joomla website via its API."""
    try:
        headers = {
            "Accept": "application/vnd.api+json",
            "User-Agent": "JoomlaArticlesMCP/1.0",
            "Authorization": f"Bearer {BEARER_TOKEN}",
        }
        async with httpx.AsyncClient() as client:
            response = await client.get(JOOMLA_ARTICLES_API_URL, headers=headers)
        if response.status_code == 200:
            return response.text
        else:
            return f"Failed to fetch articles: HTTP {response.status_code} - {response.text}"
    except httpx.HTTPError as e:
        return f"Error fetching articles: {str(e)}"
    except Exception as e:
        return f"Unexpected error: {str(e)}"


@mcp.tool(description="Retrieve all categories from the Joomla website.")
async def get_joomla_categories() -> str:
    """Retrieve all categories from the Joomla website via its API."""
    try:
        headers = {
            "Accept": "application/vnd.api+json",
            "User-Agent": "JoomlaArticlesMCP/1.0",
            "Authorization": f"Bearer {BEARER_TOKEN}",
        }
        async with httpx.AsyncClient() as client:
            response = await client.get(JOOMLA_CATEGORIES_API_URL, headers=headers)
        if response.status_code != 200:
            return f"Failed to fetch categories: HTTP {response.status_code} - {response.text}"
        try:
            data = json.loads(response.text)
            categories = data.get("data", [])
            if not isinstance(categories, list):
                return f"Error: Expected a list of categories, got {type(categories).__name__}: {response.text}"
            if not categories:
                return "No categories found."
            result = "Available categories:\n"
            for category in categories:
                attributes = category.get("attributes", {})
                category_id = attributes.get("id", "N/A")
                category_title = attributes.get("title", "N/A")
                result += f"- ID: {category_id}, Title: {category_title}\n"
            return result
        except json.JSONDecodeError:
            return f"Error parsing categories response: Invalid JSON - {response.text}"
    except httpx.HTTPError as e:
        return f"Error fetching categories: {str(e)}"
    except Exception as e:
        return f"Unexpected error: {str(e)}"


@mcp.tool(description="Create a new article on the Joomla website.")
async def create_article(
    article_text: str,
    title: str = None,
    category_id: int = None,
    convert_plain_text: bool = True,
    published: bool = True,
) -> str:
    """
    Create a new article on the Joomla website via its API. User will provide title, content,
    category, and publication status.

    Args:
        article_text (str): The content of the article (plain text or HTML).
        title (str, optional): The article title. Inferred from content if not provided.
        category_id (int, optional): The ID of the category. If not provided, lists available categories.
        convert_plain_text (bool): Convert plain text to HTML if True. Defaults to True.
        published (bool): Publish the article (True for state=1, False for state=0). Defaults to True.

    Returns:
        Success message with article title and category ID, or an error message if the request fails.
    """
    try:
        if convert_plain_text:
            article_text = convert_text_to_html(article_text)
        if not title:
            title = (
                article_text[:50].strip() + "..."
                if len(article_text) > 50
                else article_text
            )
            title = title.replace("\n", " ").strip()
        alias = generate_alias(title)
        if category_id is None:
            categories_display = await get_joomla_categories()
            return f"{categories_display}\nPlease specify a category ID."
        if not isinstance(category_id, int):
            return "Error: Category ID must be an integer."
        headers = {
            "Accept": "application/vnd.api+json",
            "Content-Type": "application/json",
            "User-Agent": "JoomlaArticlesMCP/1.0",
            "Authorization": f"Bearer {BEARER_TOKEN}",
        }
        async with httpx.AsyncClient() as client:
            response = await client.get(JOOMLA_CATEGORIES_API_URL, headers=headers)
        if response.status_code != 200:
            return f"Failed to fetch categories: HTTP {response.status_code} - {response.text}"
        try:
            data = json.loads(response.text)
            categories = data.get("data", [])
            if not isinstance(categories, list) or not categories:
                return "Failed to create article: No valid categories found."
        except json.JSONDecodeError:
            return f"Failed to create article: Invalid category JSON - {response.text}"
        valid_category = any(
            category.get("attributes", {}).get("id") == category_id
            for category in categories
        )
        if not valid_category:
            return f"Error: Category ID {category_id} is not valid."
        payload = {
            "alias": alias,
            "articletext": article_text,
            "catid": category_id,
            "language": "*",
            "metadesc": "",
            "metakey": "",
            "title": title,
            "state": 1 if published else 0,
        }
        async with httpx.AsyncClient() as client:
            response = await client.post(
                JOOMLA_ARTICLES_API_URL, json=payload, headers=headers
            )
        if response.status_code in (200, 201):
            status = "published" if published else "unpublished"
            return f"Successfully created {status} article '{title}' in category ID {category_id}"
        else:
            return f"Failed to create article: HTTP {response.status_code} - {response.text}"
    except httpx.HTTPError as e:
        return f"Error creating article: {str(e)}"
    except Exception as e:
        return f"Unexpected error: {str(e)}"


@mcp.tool(
    description="Manage the state of an existing article on the Joomla website (published, unpublished, archived, trashed)"
)
async def manage_article_state(article_id: int, target_state: int) -> str:
    """
    Manage the state of an existing article on the Joomla website via its API. Updates the article to the
    user-specified state (published=1, unpublished=0, archived=2, trashed=-2) if it differs from the current state.

    Args:
        article_id(int): The ID of the existing article to check and update.
        target_state: The desired state for the article (1=published, 0=unpublished, 2=archived, -2=trashed).

    Returns:
        Success message with article title, ID, and state change, or an error message if the request fails.
    """
    try:
        if not isinstance(article_id, int):
            return "Error: Article ID must be an integer."
        valid_states = {1, 0, 2, -2}
        if target_state not in valid_states:
            return f"Error: Invalid target state {target_state}. Valid states are 1 (published), 0 (unpublished), 2 (archived), -2 (trashed)."
        headers = {
            "Accept": "application/vnd.api+json",
            "Content-Type": "application/json",
            "User-Agent": "JoomlaArticlesMCP/1.0",
            "Authorization": f"Bearer {BEARER_TOKEN}",
        }
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{JOOMLA_ARTICLES_API_URL}/{article_id}", headers=headers
            )
        if response.status_code != 200:
            return f"Failed to fetch article: HTTP {response.status_code} - {response.text}"
        try:
            data = json.loads(response.text)
            article_data = data.get("data", {}).get("attributes", {})
            current_state = article_data.get("state", 0)
            title = article_data.get("title", "Unknown")
        except json.JSONDecodeError:
            return f"Failed to parse article data: Invalid JSON - {response.text}"
        state_map = {1: "published", 0: "unpublished", 2: "archived", -2: "trashed"}
        current_state_name = state_map.get(current_state, "unknown")
        target_state_name = state_map.get(target_state, "unknown")
        if current_state == target_state:
            return f"Article '{title}' (ID: {article_id}) is already in {current_state_name} state."
        payload = {"state": target_state}
        async with httpx.AsyncClient() as client:
            response = await client.patch(
                f"{JOOMLA_ARTICLES_API_URL}/{article_id}", json=payload, headers=headers
            )
        if response.status_code in (200, 204):
            return f"Successfully updated article '{title}' (ID: {article_id}) from {current_state_name} to {target_state_name} state."
        else:
            return f"Failed to update article state: HTTP {response.status_code} - {response.text}"
    except httpx.HTTPError as e:
        return f"Error updating article state: {str(e)}"
    except Exception as e:
        return f"Unexpected error: {str(e)}"


# A delete endpoint is available, but during testing, there was a possibility of deleting the wrong article.
# A better implementation is to change the article's state to "trashed", allowing for recovery in the event of accidental deletion.


@mcp.tool(
    description="Delete an article by moving to the trashed state on the Joomla website, allowing recovery."
)
async def move_article_to_trash(article_id: int, expected_title: str = None) -> str:
    """
    Delete an article by moving it to the trashed state (-2) on the Joomla website via its API.
    Verifies article existence and optionally checks the title to prevent moving the wrong article.
    The article remains in the database for potential recovery.

    Args:
        article_id(int): The ID of the article to move to trash.
        expected_title: Optional title to verify the correct article (case-insensitive partial match).

    Returns:
        Result string indicating success or failure.
    """
    try:
        if not isinstance(article_id, int):
            return "Error: Article ID must be an integer."
        headers = {
            "Accept": "application/vnd.api+json",
            "Content-Type": "application/json",
            "User-Agent": "JoomlaArticlesMCP/1.0",
            "Authorization": f"Bearer {BEARER_TOKEN}",
        }
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{JOOMLA_ARTICLES_API_URL}/{article_id}", headers=headers
            )
        if response.status_code != 200:
            return (
                f"Failed to find article: HTTP {response.status_code} - {response.text}"
            )
        try:
            data = json.loads(response.text)
            article_data = data.get("data", {}).get("attributes", {})
            title = article_data.get("title", "Unknown")
            current_state = article_data.get("state", 0)
        except json.JSONDecodeError:
            return f"Failed to parse article data: Invalid JSON - {response.text}"
        if expected_title:
            if not title.lower().find(expected_title.lower()) >= 0:
                return f"Error: Article ID {article_id} has title '{title}', which does not match expected title '{expected_title}'."
        if current_state == -2:
            return f"Article '{title}' (ID: {article_id}) is already in trashed state."
        return await manage_article_state(article_id, -2)
    except httpx.HTTPError as e:
        return f"Error moving article to trash: {str(e)}. Please check network connectivity or Joomla API availability."
    except Exception as e:
        return f"Unexpected error: {str(e)}. Please try again or contact support."


@mcp.tool(description="Update an existing article on the Joomla website.")
async def update_article(
    article_id: int,
    title: str = None,
    introtext: str = None,
    fulltext: str = None,
    metadesc: str = None,
    convert_plain_text: bool = True,
) -> str:
    """
    Update an existing article on the Joomla website via its API. Allows updating the title, introtext, fulltext,
    and meta description. Provide both introtext and fulltext together for articles with separate introductory
    and main content, or provide only fulltext for articles where a single body of content is sufficient.
    Introtext alone is not sufficient and will be ignored unless accompanied by fulltext.
    Before updating, confirm the article's title and ID are correct.
    Only articles with both introtext and fulltext will be updated.

    Args:
        article_id(int): The ID of the article to update. Don't prompt user for article_id, infer it by running the get_joomla_articles tool.
        title (str, optional): New title for the article.
        introtext (str, optional): Introductory text (requires fulltext if provided).
        fulltext: Optional full content for the article (plain text or HTML). Used as primary content if provided alone,
        or as main content if provided with introtext.
        metadesc: Optional meta description for the article.
        convert_plain_text: Whether to auto-convert plain text to HTML for introtext and fulltext (default: True).

    Returns:
        Result string indicating success or failure.
    """
    try:
        if not isinstance(article_id, int):
            return "Error: Article ID must be an integer."
        if not any([title, introtext, fulltext, metadesc]):
            return "Error: At least one of title, introtext, fulltext, or metadesc must be provided."
        headers = {
            "Accept": "application/vnd.api+json",
            "Content-Type": "application/json",
            "User-Agent": "JoomlaArticlesMCP/1.0",
            "Authorization": f"Bearer {BEARER_TOKEN}",
        }
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{JOOMLA_ARTICLES_API_URL}/{article_id}", headers=headers
            )
        if response.status_code != 200:
            return (
                f"Failed to find article: HTTP {response.status_code} - {response.text}"
            )
        try:
            data = json.loads(response.text)
            article_data = data.get("data", {}).get("attributes", {})
            current_title = article_data.get("title", "Unknown")
        except json.JSONDecodeError:
            return f"Failed to parse article data: Invalid JSON - {response.text}"
        payload = {}
        if title:
            payload["title"] = title
            payload["alias"] = generate_alias(title)
        if metadesc:
            payload["metadesc"] = metadesc
        if introtext:
            payload["introtext"] = (
                convert_text_to_html(introtext) if convert_plain_text else introtext
            )
            if fulltext:
                payload["fulltext"] = (
                    convert_text_to_html(fulltext) if convert_plain_text else fulltext
                )
        elif fulltext:
            payload["articletext"] = (
                convert_text_to_html(fulltext) if convert_plain_text else fulltext
            )
        async with httpx.AsyncClient() as client:
            response = await client.patch(
                f"{JOOMLA_ARTICLES_API_URL}/{article_id}", json=payload, headers=headers
            )
        if response.status_code in (200, 204):
            updated_fields = []
            if title:
                updated_fields.append(f"title to '{title}'")
            if introtext:
                updated_fields.append("introtext")
            if fulltext:
                updated_fields.append("fulltext" if introtext else "body")
            if metadesc:
                updated_fields.append("metadesc")
            return f"Successfully updated article '{current_title}' (ID: {article_id}) {', '.join(updated_fields)}."
        else:
            error_detail = response.text
            return f"Failed to update article: HTTP {response.status_code} - {error_detail}. This may indicate a server-side issue or insufficient permissions. Please verify the bearer token permissions and Joomla server logs."
    except httpx.HTTPError as e:
        return f"Error updating article: {str(e)}. Please check network connectivity or Joomla API availability."
    except Exception as e:
        return f"Unexpected error: {str(e)}. Please try again or contact support."


# Hugging Face Tools
@mcp.tool(description="Generate article content using Hugging Face models.")
async def generate_article_with_huggingface(
    topic: str,
    model: str = "microsoft/DialoGPT-medium",
    style: str = "informative",
    max_tokens: int = 500
) -> str:
    """
    Generate article content using Hugging Face models.
    
    Args:
        topic (str): The topic or subject for the article
        model (str): Hugging Face model to use for generation
        style (str): Writing style (informative, casual, formal, technical)
        max_tokens (int): Maximum number of tokens to generate
    
    Returns:
        str: Generated article content
    """
    prompt = f"Write a {style} article about {topic}. Make it engaging and informative:"
    return await generate_with_huggingface(prompt, model, max_tokens)


@mcp.tool(description="Summarize article content using Hugging Face models.")
async def summarize_article_content(
    content: str,
    max_length: int = 150,
    min_length: int = 30
) -> str:
    """
    Summarize article content using Hugging Face models.
    
    Args:
        content (str): The article content to summarize
        max_length (int): Maximum length of the summary
        min_length (int): Minimum length of the summary
    
    Returns:
        str: Summarized content
    """
    return await summarize_text_hf(content, max_length)


@mcp.tool(description="Analyze sentiment of article content using Hugging Face models.")
async def analyze_article_sentiment(content: str) -> str:
    """
    Analyze sentiment of article content using Hugging Face models.
    
    Args:
        content (str): The article content to analyze
    
    Returns:
        str: Sentiment analysis result
    """
    return await analyze_sentiment_hf(content)


@mcp.tool(description="Classify and tag article content using Hugging Face models.")
async def classify_article_content(
    content: str,
    candidate_labels: List[str] = None
) -> str:
    """
    Classify and tag article content using Hugging Face models.
    
    Args:
        content (str): The article content to classify
        candidate_labels (List[str]): List of possible labels/categories
    
    Returns:
        str: Classification results
    """
    if not candidate_labels:
        candidate_labels = [
            "technology", "business", "health", "science", "sports", 
            "entertainment", "politics", "education", "travel", "lifestyle"
        ]
    
    if hf_client:
        try:
            response = await asyncio.to_thread(
                hf_client.zero_shot_classification,
                content[:1000],  # Limit content length for API
                candidate_labels
            )
            results = []
            for label, score in zip(response['labels'], response['scores']):
                results.append(f"{label}: {score:.3f}")
            return "Content classification:\n" + "\n".join(results)
        except Exception as e:
            return f"Error classifying with Hugging Face API: {str(e)}"
    
    # Fallback to local model
    if text_classifier:
        try:
            result = await asyncio.to_thread(
                text_classifier,
                content[:1000],
                candidate_labels
            )
            results = []
            for label, score in zip(result['labels'], result['scores']):
                results.append(f"{label}: {score:.3f}")
            return "Content classification:\n" + "\n".join(results)
        except Exception as e:
            return f"Error classifying with local model: {str(e)}"
    
    return "Error: No classification service available."


@mcp.tool(description="Translate article content using Hugging Face models.")
async def translate_article_content(
    content: str,
    target_language: str = "french",
    source_language: str = "english"
) -> str:
    """
    Translate article content using Hugging Face models.
    
    Args:
        content (str): The article content to translate
        target_language (str): Target language for translation
        source_language (str): Source language of the content
    
    Returns:
        str: Translated content
    """
    if not hf_client:
        return "Error: Hugging Face API token not configured. Please set HUGGINGFACE_API_TOKEN environment variable."
    
    try:
        # Use a translation model based on language pair
        model_map = {
            ("english", "french"): "Helsinki-NLP/opus-mt-en-fr",
            ("english", "spanish"): "Helsinki-NLP/opus-mt-en-es",
            ("english", "german"): "Helsinki-NLP/opus-mt-en-de",
            ("english", "italian"): "Helsinki-NLP/opus-mt-en-it",
            ("french", "english"): "Helsinki-NLP/opus-mt-fr-en",
            ("spanish", "english"): "Helsinki-NLP/opus-mt-es-en",
            ("german", "english"): "Helsinki-NLP/opus-mt-de-en",
        }
        
        model_key = (source_language.lower(), target_language.lower())
        model = model_map.get(model_key, "Helsinki-NLP/opus-mt-en-fr")
        
        response = await asyncio.to_thread(
            hf_client.translation,
            content,
            model=model
        )
        return response['translation_text']
    except Exception as e:
        return f"Error translating content: {str(e)}"


# Hybrid AI + Joomla Tools
@mcp.tool(description="Create an AI-generated article and publish it to Joomla.")
async def create_ai_article_and_publish(
    topic: str,
    ai_service: str = "gemini",
    style: str = "informative",
    length: str = "medium",
    category_id: int = None,
    published: bool = True,
    generate_meta: bool = True
) -> str:
    """
    Create an AI-generated article and publish it directly to Joomla.
    
    Args:
        topic (str): The topic for the article
        ai_service (str): AI service to use ("gemini" or "huggingface")
        style (str): Writing style
        length (str): Article length (short, medium, long)
        category_id (int): Joomla category ID
        published (bool): Whether to publish immediately
        generate_meta (bool): Whether to generate meta description
    
    Returns:
        str: Result of the article creation and publishing process
    """
    try:
        # Generate content using selected AI service
        if ai_service.lower() == "gemini":
            content = await generate_article_with_gemini(topic, style, length, "general", True)
        else:
            max_tokens = {"short": 300, "medium": 500, "long": 800}.get(length, 500)
            content = await generate_article_with_huggingface(topic, "microsoft/DialoGPT-medium", style, max_tokens)
        
        if content.startswith("Error:"):
            return content
        
        # Extract title from generated content or generate one
        lines = content.split('\n')
        title = None
        article_text = content
        
        # Try to find a title in the first few lines
        for line in lines[:3]:
            line = line.strip()
            if line and (line.startswith('#') or len(line) < 100):
                title = line.replace('#', '').strip()
                # Remove title from article text
                article_text = '\n'.join(lines[1:]).strip()
                break
        
        if not title:
            title = f"Article about {topic}"
        
        # Generate meta description if requested
        metadesc = None
        if generate_meta and ai_service.lower() == "gemini":
            meta_result = await generate_title_meta_with_gemini(article_text)
            if not meta_result.startswith("Error:"):
                # Extract meta description from the result
                for line in meta_result.split('\n'):
                    if line.startswith("Meta Description:"):
                        metadesc = line.replace("Meta Description:", "").strip()
                        break
        
        # Create the article in Joomla
        result = await create_article(
            article_text=article_text,
            title=title,
            category_id=category_id,
            convert_plain_text=True,
            published=published
        )
        
        # Add meta description if generated and article was created successfully
        if metadesc and "successfully created" in result.lower():
            # Extract article ID from result to update with meta description
            import re
            id_match = re.search(r'ID: (\d+)', result)
            if id_match:
                article_id = int(id_match.group(1))
                await update_article(article_id, metadesc=metadesc)
                result += f"\nMeta description added: {metadesc}"
        
        return f"AI-Generated Article Creation Result:\n{result}\n\nGenerated using: {ai_service.title()}"
        
    except Exception as e:
        return f"Error creating AI-generated article: {str(e)}"


@mcp.tool(description="Enhance an existing Joomla article using AI.")
async def enhance_existing_joomla_article(
    article_id: int,
    enhancement_type: str = "improve_readability",
    ai_service: str = "gemini",
    target_audience: str = "general"
) -> str:
    """
    Enhance an existing Joomla article using AI services.
    
    Args:
        article_id (int): ID of the article to enhance
        enhancement_type (str): Type of enhancement to apply
        ai_service (str): AI service to use ("gemini" or "huggingface")
        target_audience (str): Target audience for the enhancement
    
    Returns:
        str: Result of the enhancement process
    """
    try:
        # First, get the existing article
        articles_response = await get_joomla_articles()
        if articles_response.startswith("Error:") or articles_response.startswith("Failed"):
            return f"Error retrieving articles: {articles_response}"
        
        # Parse articles to find the specific one
        try:
            articles_data = json.loads(articles_response)
            target_article = None
            
            for article in articles_data.get("data", []):
                if article.get("attributes", {}).get("id") == str(article_id):
                    target_article = article.get("attributes", {})
                    break
            
            if not target_article:
                return f"Article with ID {article_id} not found."
            
            current_content = target_article.get("articletext", "") or target_article.get("fulltext", "")
            current_title = target_article.get("title", "")
            
            if not current_content:
                return f"No content found for article ID {article_id}."
            
        except json.JSONDecodeError:
            return "Error parsing articles data."
        
        # Enhance content using selected AI service
        if ai_service.lower() == "gemini":
            enhanced_content = await enhance_article_with_gemini(current_content, enhancement_type, target_audience)
        else:
            # For Hugging Face, use summarization or basic text generation
            if enhancement_type == "summarize":
                enhanced_content = await summarize_text_hf(current_content)
            else:
                prompt = f"Improve this article content for {target_audience} audience: {current_content[:500]}..."
                enhanced_content = await generate_with_huggingface(prompt)
        
        if enhanced_content.startswith("Error:"):
            return enhanced_content
        
        # Update the article with enhanced content
        update_result = await update_article(
            article_id=article_id,
            fulltext=enhanced_content,
            convert_plain_text=True
        )
        
        return f"Article Enhancement Result:\n{update_result}\n\nEnhancement type: {enhancement_type}\nAI service used: {ai_service.title()}"
        
    except Exception as e:
        return f"Error enhancing article: {str(e)}"


@mcp.tool(description="Analyze and categorize multiple Joomla articles using AI.")
async def analyze_joomla_articles_with_ai(
    analysis_type: str = "sentiment",
    limit: int = 10
) -> str:
    """
    Analyze multiple Joomla articles using AI services.
    
    Args:
        analysis_type (str): Type of analysis (sentiment, classification, summary)
        limit (int): Maximum number of articles to analyze
    
    Returns:
        str: Analysis results for the articles
    """
    try:
        # Get all articles
        articles_response = await get_joomla_articles()
        if articles_response.startswith("Error:") or articles_response.startswith("Failed"):
            return f"Error retrieving articles: {articles_response}"
        
        try:
            articles_data = json.loads(articles_response)
            articles = articles_data.get("data", [])[:limit]
            
            if not articles:
                return "No articles found to analyze."
            
            results = []
            
            for article in articles:
                attributes = article.get("attributes", {})
                article_id = attributes.get("id", "Unknown")
                title = attributes.get("title", "No title")
                content = attributes.get("articletext", "") or attributes.get("fulltext", "")
                
                if not content:
                    continue
                
                # Perform analysis based on type
                if analysis_type == "sentiment":
                    analysis_result = await analyze_sentiment_hf(content[:500])
                elif analysis_type == "classification":
                    analysis_result = await classify_article_content(content[:500])
                elif analysis_type == "summary":
                    analysis_result = await summarize_text_hf(content, 100)
                else:
                    analysis_result = "Unknown analysis type"
                
                results.append(f"Article ID {article_id}: {title}\n{analysis_result}\n")
            
            return f"AI Analysis Results ({analysis_type}):\n\n" + "\n".join(results)
            
        except json.JSONDecodeError:
            return "Error parsing articles data."
        
    except Exception as e:
        return f"Error analyzing articles: {str(e)}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
