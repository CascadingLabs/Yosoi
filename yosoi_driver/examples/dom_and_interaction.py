"""Query DOM elements, click buttons, and type into inputs."""

import asyncio

from yosoi_driver import BrowserSession

FORM_PAGE = """data:text/html,
<html>
<body>
  <h1 id="greeting">Hello</h1>
  <input id="name" type="text" placeholder="Your name" />
  <button id="btn" onclick="
    document.getElementById('greeting').textContent =
      'Hello, ' + document.getElementById('name').value + '!';
  ">Greet</button>
</body>
</html>
"""


async def main() -> None:
    """Query DOM elements, type into an input, and click a button."""
    async with BrowserSession(headless=True) as session:
        page = await session.new_page(FORM_PAGE)

        # Query a single element (returns outer HTML or None)
        heading = await page.query_selector('#greeting')
        print(f'Heading HTML: {heading}')

        # Query multiple elements
        all_inputs = await page.query_selector_all('input')
        print(f'Found {len(all_inputs)} input(s)')

        # Type into the input and click the button
        await page.type_into('#name', 'World')
        await page.click_element('#btn')

        # Check the updated heading
        updated = await page.query_selector('#greeting')
        print(f'Updated heading: {updated}')

        # Missing selectors return None
        missing = await page.query_selector('#does-not-exist')
        print(f'Missing element: {missing}')

        await page.close()


if __name__ == '__main__':
    asyncio.run(main())
