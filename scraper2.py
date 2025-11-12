
import os
import json
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

# Prompt to extract CSS selectors for article data fields
def get_prompt(missing_fields=None):
    base_prompt = """
You have access to the HTML source code of the webpage. Examine the actual HTML structure, element tags, attributes, classes, and IDs to identify CSS selectors.

CRITICAL INSTRUCTIONS:
1. Look at the HTML source code that was provided to you - examine the actual HTML tags, attributes, classes, and IDs
2. You MUST find a valid CSS selector for each field. Do NOT return "NA" or null values
3. If an element exists on the page, there is always a way to select it with CSS
4. Examine the HTML structure carefully - look at the actual tags, classes, IDs, and attributes in the source code

For each field, provide a CSS selector string. Prioritize high-quality selectors in this order:
1. aria-label attributes (e.g., '[aria-label="headline"]')
2. data-testid attributes (e.g., '[data-testid="author"]')
3. id attributes (e.g., '#article-title')
4. class attributes with semantic names (e.g., '.article-headline')
5. CSS-only selectors as a last resort (e.g., 'h1.entry-title', 'time', 'article p')

Extract selectors for:
1. Headline - the main title of the article (usually an h1 tag) - look at the HTML to see the actual h1 element and its attributes
2. Author - the author's name (look for author links, bylines, or author metadata) - examine the HTML for author-related elements
3. Date - the publication date (look for time tags, date classes, or datetime attributes) - check the HTML for <time> tags or date elements
4. Body text - the main article content/body text (look for article tags, main content divs, or paragraph containers) - examine the HTML structure for content containers
5. Related content - any related articles, tags, or additional content mentioned (optional, but try to find it)

DETAILED HTML EXAMINATION INSTRUCTIONS:
- For "date": Search the HTML for <time> tags, elements with datetime attributes, or elements containing date text. Look at the actual HTML structure. Common patterns: 'time', '[datetime]', '.date', '.published', '.post-date', elements with date-related classes
- For "body_text": Search the HTML for <article> tags, main content containers, or paragraph collections. Look at the actual HTML structure. Common patterns: 'article', 'article p', '.entry-content', '.post-content', 'main p', content divs with specific classes
- Examine the HTML source code line by line if needed - look for the actual element tags and their attributes
- If you cannot find a specific attribute, use element types, classes, or structural selectors based on what you see in the HTML
- NEVER return "NA" - always provide a valid CSS selector based on the HTML structure you can see

Return ONLY a valid JSON object with these keys: headline, author, date, body_text, related_content.
Each value must be a valid CSS selector string (not "NA", not null, not empty) based on the actual HTML source code you examined.
"""
    if missing_fields:
        base_prompt += f"\n\nATTENTION: The following fields were not found in previous attempts: {', '.join(missing_fields)}. Please examine the HTML source code more carefully. Look through the entire HTML document for these elements. Search for all possible variations - check for different class names, different tag structures, and different attribute patterns."
    
    # Add explicit instruction to use the HTML that was fetched
    base_prompt += "\n\nREMINDER: The HTML source code of the webpage has been fetched and is available in your context. Use that HTML to identify the exact CSS selectors. Do not guess - examine the actual HTML tags, attributes, classes, and IDs that are present in the source code."
    
    return base_prompt

# Function to parse result and extract selectors
def parse_result(result):
    """Parse the result from SmartScraperGraph and extract selectors."""
    selectors = None
    if isinstance(result, str):
        # Try to find JSON in the string
        try:
            # Look for JSON object in the string
            start_idx = result.find('{')
            end_idx = result.rfind('}') + 1
            if start_idx != -1 and end_idx > start_idx:
                json_str = result[start_idx:end_idx]
                selectors = json.loads(json_str)
            else:
                # If no JSON found, try parsing the whole string
                selectors = json.loads(result)
        except json.JSONDecodeError:
            print("\nWarning: Could not parse result as JSON.")
            return None
    elif isinstance(result, dict):
        selectors = result
    else:
        print(f"\nWarning: Unexpected result type: {type(result)}")
        return None
    return selectors

# Function to check if selectors are valid
def validate_selectors(selectors):
    """Check if all required selectors are populated (not NA, null, or empty)."""
    if not selectors or not isinstance(selectors, dict):
        return False, []
    
    required_fields = ['headline', 'author', 'date', 'body_text']
    missing = []
    
    for field in required_fields:
        value = selectors.get(field, '').strip()
        if not value or value.upper() == 'NA' or value.lower() == 'null' or value == '':
            missing.append(field)
    
    return len(missing) == 0, missing

# Retry loop until all required selectors are found
max_attempts = 10
attempt = 0
selectors = None
output_file = "selectors.json"

print(f"Extracting selectors from: {url}")
print("=" * 80)

while attempt < max_attempts:
    attempt += 1
    print(f"\n--- Attempt {attempt}/{max_attempts} ---")
    
    # Get prompt, including missing fields if this is a retry
    missing_fields = []
    if selectors:
        _, missing_fields = validate_selectors(selectors)
    
    prompt = get_prompt(missing_fields if missing_fields else None)
    
    # Create the SmartScraperGraph instance
    smart_scraper_graph = SmartScraperGraph(
        prompt=prompt,
        source=url,
        config=graph_config
    )
    
    # Run the pipeline
    result = smart_scraper_graph.run()
    
    # Parse and validate the JSON result
    print("\nRaw result:")
    print("=" * 80)
    print(result)
    
    # Parse the result
    selectors = parse_result(result)
    
    if selectors is None:
        print("\nFailed to parse result. Retrying...")
        continue
    
    # Validate selectors
    is_valid, missing = validate_selectors(selectors)
    
    # Print current selectors
    print("\nExtracted Selectors:")
    print("=" * 80)
    print(json.dumps(selectors, indent=2, ensure_ascii=False))
    
    if is_valid:
        print("\n✓ All required selectors found!")
        break
    else:
        print(f"\n✗ Missing selectors: {', '.join(missing)}")
        if attempt < max_attempts:
            print("Retrying with improved prompt...")
        else:
            print(f"\nWarning: Reached maximum attempts ({max_attempts}). Some selectors may still be missing.")

# Save selectors to JSON file
with open(output_file, 'w', encoding='utf-8') as f:
    json.dump(selectors, f, indent=2, ensure_ascii=False)

print(f"\nSelectors saved to: {output_file}")

