

# Joomla MCP Server

[![smithery badge](https://smithery.ai/badge/@nasoma/joomla-mcp-server)](https://smithery.ai/server/@nasoma/joomla-mcp-server)
[![MseeP.ai Security Assessment Badge](https://mseep.net/pr/nasoma-joomla-mcp-server-badge.png)](https://mseep.ai/app/nasoma-joomla-mcp-server)

[![Verified on MseeP](https://mseep.ai/badge.svg)](https://mseep.ai/app/7a5e4ad1-6f70-4495-94e1-dc3fcc568e65)


## Table of Contents
- [Introduction](#introduction)
- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Available Tools](#available-tools)
- [Security Considerations](#security-considerations)

## Introduction
The Joomla MCP (Model Context Protocol) Server enables AI assistants, such as Claude, to interact with Joomla websites via the Joomla Web Services API. It provides tools to manage articles using an AI assistant.

## Features

### Core Joomla Integration
- Retrieve all articles from a Joomla website
- List all content categories
- Create new articles
- Manage article states (published, unpublished, trashed, or archived)
- Delete articles
- Update articles (requires both introtext and fulltext, with a "Read more" break)

### AI-Powered Content Generation
- **Google Gemini Integration**: Generate high-quality articles, enhance existing content, and create SEO-optimized titles and meta descriptions
- **Hugging Face Integration**: Access to hundreds of AI models for text generation, summarization, sentiment analysis, classification, and translation
- **Hybrid AI Workflows**: Combine AI generation with direct Joomla publishing for streamlined content creation

### Advanced AI Features
- Content enhancement and optimization
- Automated sentiment analysis
- Article classification and tagging
- Multi-language translation support
- Bulk article analysis and processing
- SEO optimization assistance

## Requirements
- Python 3.11+
- Joomla 4.x or 5.x with the Web Services API plugin enabled
- API Bearer token for authentication
- **Optional**: Google Gemini API key for advanced AI features
- **Optional**: Hugging Face API token for additional AI models


## Installation


### Create a Joomla API Token

1. Access User Profile: Log in to the Joomla Administrator interface and navigate to the Users menu, then select Manage.

2. Edit Super User: Find and click on the Super User account (or the desired user) to edit their profile.

3. Generate Token: Go to the Joomla API Token tab, click the Generate button, and copy the displayed token.

### Set up AI Services (Optional)

#### Google Gemini API Setup
1. Visit the [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Create a new API key or use an existing one
3. Copy the API key for use in the environment configuration

#### Hugging Face API Setup
1. Visit [Hugging Face](https://huggingface.co/settings/tokens)
2. Create a new access token with read permissions
3. Copy the token for use in the environment configuration

**Note**: AI services are optional. The server will work with just Joomla functionality if no AI API keys are provided. Some AI features can work offline using local models, though they may require additional setup time for model downloads.

###  Install the Project/Server locally
1. Clone the repository:
```

git clone https://github.com/nasoma/joomla-mcp-server.git
cd joomla-mcp-server

```
2. Set up a virtual environment and install dependencies using `uv` (a Python dependency manager, see [uv documentation](https://github.com/astral-sh/uv)). If uv is installed run:

```
uv sync 
```


### Installing on Claude or other AI assistants
#### Claude Desktop

Add this to your `claude_desktop_config.json`:


```json
{
  "mcpServers": {
    "Joomla Articles MCP": {
      "command": "{{PATH_TO_UV}}",
      "args": [
        "--directory",
        "{{PATH_TO_PROJECT}}",
        "run",
        "main.py"
      ],
      "env": {
        "JOOMLA_BASE_URL": "<your_joomla_website_url>",
        "BEARER_TOKEN": "<your_joomla_api_token>",
        "GEMINI_API_KEY": "<your_gemini_api_key>",
        "HUGGINGFACE_API_TOKEN": "<your_huggingface_api_token>",
        "GEMINI_MODEL": "gemini-1.5-flash"
      }
    }
  }
}


```
Replace `{{PATH_TO_UV}}` with the path to `uv` (run `which uv` to find it) and `{{PATH_TO_PROJECT}}` with the project directory path (run `pwd` in the repository root).




## Available Tools

### 1. get_joomla_articles()
Retrieves all articles from the Joomla website via its API.



### 2. get_joomla_categories()
Retrieves all categories from the Joomla website and formats them in a readable list.


### 3. create_article()
Creates a new article on the Joomla website via its API.

**Parameters:**
- `article_text` (required): The content of the article (plain text or HTML)
- `title` (optional): The article title (inferred from content if not provided)
- `category_id` (optional): The category ID for the article
- `convert_plain_text` (optional, default: True): Auto-converts plain text to HTML
- `published` (optional, default: True): Publishes the article immediately

### 4. manage_article_state()
Manages the state of an existing article on the Joomla website via its API.

**Parameters:**
- `article_id` (required): The ID of the existing article to check and update
- `target_state` (required): The desired state for the article (1=published, 0=unpublished, 2=archived, -2=trashed)

### 5. delete_article()
Deletes an article from the Joomla website via its API.

**Parameters:**
- `article_id` (required): The ID of the article to delete

### 6. update_article()
Updates an existing article on the Joomla website via its API. Both `introtext` and `fulltext` are required to align with Joomla's article structure (introtext for the teaser, fulltext for the content after a "Read more" break).

**Parameters:**
- `article_id` (required): The ID of the article to update
- `title` (optional): New title for the article
- `introtext` (required): Introductory text for the article (plain text or HTML)
- `fulltext` (required): Full content for the article (plain text or HTML)
- `metadesc` (optional): Meta description for the article

## AI-Powered Tools

### Google Gemini Tools

#### 7. generate_article_with_gemini()
Generate high-quality article content using Google Gemini AI.

**Parameters:**
- `topic` (required): The topic or subject for the article
- `style` (optional): Writing style (informative, persuasive, casual, formal, technical)
- `length` (optional): Article length (short, medium, long)
- `target_audience` (optional): Target audience (general, technical, beginner, expert)
- `include_title` (optional): Whether to include a title in the generated content

#### 8. enhance_article_with_gemini()
Enhance existing article content using Google Gemini AI.

**Parameters:**
- `content` (required): The existing article content to enhance
- `enhancement_type` (optional): Type of enhancement (improve_readability, add_details, make_engaging, fix_grammar, optimize_seo)
- `target_audience` (optional): Target audience for the enhancement

#### 9. generate_title_meta_with_gemini()
Generate SEO-optimized titles and meta descriptions using Google Gemini AI.

**Parameters:**
- `content` (required): The article content to analyze
- `focus_keyword` (optional): Optional focus keyword to include
- `title_style` (optional): Style for the title (engaging, professional, clickbait, descriptive)

### Hugging Face Tools

#### 10. generate_article_with_huggingface()
Generate article content using Hugging Face models.

**Parameters:**
- `topic` (required): The topic or subject for the article
- `model` (optional): Hugging Face model to use for generation
- `style` (optional): Writing style (informative, casual, formal, technical)
- `max_tokens` (optional): Maximum number of tokens to generate

#### 11. summarize_article_content()
Summarize article content using Hugging Face models.

**Parameters:**
- `content` (required): The article content to summarize
- `max_length` (optional): Maximum length of the summary
- `min_length` (optional): Minimum length of the summary

#### 12. analyze_article_sentiment()
Analyze sentiment of article content using Hugging Face models.

**Parameters:**
- `content` (required): The article content to analyze

#### 13. classify_article_content()
Classify and tag article content using Hugging Face models.

**Parameters:**
- `content` (required): The article content to classify
- `candidate_labels` (optional): List of possible labels/categories

#### 14. translate_article_content()
Translate article content using Hugging Face models.

**Parameters:**
- `content` (required): The article content to translate
- `target_language` (optional): Target language for translation
- `source_language` (optional): Source language of the content

### Hybrid AI + Joomla Tools

#### 15. create_ai_article_and_publish()
Create an AI-generated article and publish it directly to Joomla.

**Parameters:**
- `topic` (required): The topic for the article
- `ai_service` (optional): AI service to use ("gemini" or "huggingface")
- `style` (optional): Writing style
- `length` (optional): Article length (short, medium, long)
- `category_id` (optional): Joomla category ID
- `published` (optional): Whether to publish immediately
- `generate_meta` (optional): Whether to generate meta description

#### 16. enhance_existing_joomla_article()
Enhance an existing Joomla article using AI services.

**Parameters:**
- `article_id` (required): ID of the article to enhance
- `enhancement_type` (optional): Type of enhancement to apply
- `ai_service` (optional): AI service to use ("gemini" or "huggingface")
- `target_audience` (optional): Target audience for the enhancement

#### 17. analyze_joomla_articles_with_ai()
Analyze and categorize multiple Joomla articles using AI services.

**Parameters:**
- `analysis_type` (optional): Type of analysis (sentiment, classification, summary)
- `limit` (optional): Maximum number of articles to analyze

## Security Considerations

### Joomla Security
- The Joomla API Token has access to your site. Treat it the same way you treat your passwords.
- The server sanitizes HTML content to prevent XSS attacks
- Ensure your Joomla website uses HTTPS to secure API communications.

### AI Services Security
- **API Keys**: Store your Gemini and Hugging Face API keys securely. Never commit them to version control.
- **Content Privacy**: Be aware that content sent to AI services may be processed on external servers. Review the privacy policies of Google Gemini and Hugging Face.
- **Rate Limiting**: AI services have rate limits. The server includes error handling for API failures.
- **Content Validation**: Always review AI-generated content before publishing to ensure accuracy and appropriateness.
- **Local Models**: For sensitive content, consider using local Hugging Face models instead of API-based services.

## License
This project is licensed under the MIT License. 
