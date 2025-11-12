import os
from dotenv import load_dotenv
from scrapegraphai.graphs import SmartScraperGraph
from langchain_google_genai import ChatGoogleGenerativeAI

# Load environment variables from .env file
load_dotenv()

# Retrieve the Gemini API key from environment variables
gemini_api_key = os.getenv('GEMINI_KEY')

if not gemini_api_key:
    raise ValueError(
        "GEMINI_KEY not found in environment variables. "
        "Please create a .env file with your GEMINI_KEY. "
        "See .env.example for reference."
    )

# Create a LangChain model instance
llm_model = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    google_api_key=gemini_api_key,
    temperature=0.1,
)

# Define the configuration for the scraping pipeline
graph_config = {
    "llm": {
        "model_instance": llm_model,
        "model_tokens": 1000000  # Gemini 2.0 Flash has a large context window
    },
    "verbose": True,
    "headless": False,
}

# Target URL
url = "https://virginiabusiness.com/new-documents-reveal-scope-of-googles-chesterfield-data-center-campus/?utm_campaign=TickerTick&utm_medium=website&utm_source=tickertick.com"

# Prompt to extract structured article data
prompt = """
Extract the following information from this article:
1. Headline - the main title of the article
2. Author - the author's name
3. Date - the publication date
4. Body text - the main article content/body text
5. Related content - any related articles, tags, or additional content mentioned

Format the output as structured data with clear labels for each field.
"""

# Create the SmartScraperGraph instance
smart_scraper_graph = SmartScraperGraph(
    prompt=prompt,
    source=url,
    config=graph_config
)

# Run the pipeline
print(f"Scraping article from: {url}")
print("=" * 80)
result = smart_scraper_graph.run()

# Print the extracted information
print("\nExtracted Article Data:")
print("=" * 80)
print(result)

