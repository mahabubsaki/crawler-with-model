import re
from playwright.async_api import async_playwright
from collections import deque
import asyncio
import time
from pathlib import Path


websites = [
    {
        "name": "electron",
        "url": "https://www.electron.build/",
        "root_url": "https://www.electron.build",
        "priority_keywords": []
    },
   
   ]
async def get_page_content(page, url, base_url, root_url):
    """Get page content using Playwright"""
    try:
        print(f"🔍 Loading: {url}")
        await page.goto(url, wait_until='networkidle', timeout=30000)
        
        # Wait for content to load
        await asyncio.sleep(2)
        
        # Get page title and content
        title = await page.title()
        content = await page.evaluate('''() => {
            // Remove scripts, styles, and navigation
            const elementsToRemove = document.querySelectorAll('script, style, nav, header, footer, .sidebar, .menu');
            elementsToRemove.forEach(el => el.remove());
            
            // Get main content area
            const main = document.querySelector('main') || document.querySelector('.content') || document.body;
            return main ? main.innerText : document.body.innerText;
        }''')
        
        # Get all internal links
        links = await page.evaluate(f'''() => {{
            const links = [];
            const anchors = document.querySelectorAll('a[href]');
            anchors.forEach(a => {{
                const href = a.href;
                if (href.includes('{root_url}') && !href.includes('#')) {{
                    links.push(href);
                }}
            }});
            return [...new Set(links)];
        }}''')
        print(links)
        
        return {
            'url': url,
            'title': title,
            'content': content.strip(),
            'links': links
        }
        
    except Exception as e:
        print(f"❌ Error loading {url}: {e}")
        return None

async def crawl_website(website_config):
    """Crawl a single website using automatic link discovery with AI content filtering"""
    crawl_start_time = time.time()
    print(f"🚀 Starting crawling for {website_config['name']} website...")
    
    # Create data directory for this website
    data_dir = Path(f"./docs/{website_config['name']}")
    data_dir.mkdir(parents=True, exist_ok=True)
    
    base_url = website_config['url']
    root_url = website_config['root_url']
    visited_urls = set()
    crawled_content = {}
    
    async with async_playwright() as p:
        # Launch browser
        browser = await p.chromium.launch(headless=True)
        
        try:
            page = await browser.new_page()
            await page.set_extra_http_headers({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
            
            # Start with just the homepage to discover all links
            print(f"🔍 Discovering all links from {website_config['name']} homepage...")
            homepage_data = await get_page_content(page, base_url, base_url,root_url)
            
            # Initialize URLs with homepage and all discovered links
            start_urls = [base_url]
            if homepage_data and homepage_data['links']:
                start_urls.extend(homepage_data['links'])
                print(f"📋 Found {len(homepage_data['links'])} initial links from homepage")
            
            # Remove duplicates and filter out unwanted URLs
            filtered_urls = []
            for url in start_urls:
                if url not in filtered_urls:
                    # Filter out unwanted patterns
                    if not any(skip in url for skip in [
                        'mailto:', 'tel:', 'javascript:', '#', 
                        '.pdf', '.zip', '.exe', '.dmg',
                        '/feed', '/rss', '/xml',
                        'twitter.com', 'facebook.com', 'github.com', 'linkedin.com'
                    ]):
                        filtered_urls.append(url)
            
            start_urls = filtered_urls[:100]  # Limit initial discovery to prevent overwhelming
            print(f"🎯 Starting crawl with {len(start_urls)} filtered URLs")
            
            # Queue for BFS crawling
            url_queue = deque(start_urls)
            max_pages = 5000  # Reduced for faster crawling with AI filtering
            crawled_count = 0
            learning_content_count = 0
            ai_classification_time = 0
            
            while url_queue and crawled_count < max_pages:
                current_url = url_queue.popleft()
                
                if current_url in visited_urls:
                    continue
                    
                visited_urls.add(current_url)
                crawled_count += 1
                
                # Get page content
                page_data = await get_page_content(page, current_url, base_url, root_url)
                
                if page_data and page_data['content']:
                    # AI-powered content filtering with timing
                    print(f"🤖 Checking if content is educational...")
                    ai_start_time = time.time()
                    is_educational = True
                    ai_classification_time += time.time() - ai_start_time
                    
                    if is_educational:
                        learning_content_count += 1
                        # Store content
                        crawled_content[current_url] = page_data
                        
                        # Save to file immediately
                        safe_filename = re.sub(r'[^\w\-_.]', '_', current_url.replace(base_url, ''))
                        if not safe_filename:
                            safe_filename = 'homepage'
                        
                        filename = data_dir / f"{safe_filename}_{learning_content_count}.txt"
                        with open(filename, 'w', encoding='utf-8') as f:
                            f.write(f"{website_config['name'].title()} Website - {page_data['title']}\n")
                            f.write("="*80 + "\n\n")
                            f.write(f"URL: {current_url}\n")
                            f.write(f"Title: {page_data['title']}\n\n")
                            f.write(page_data['content'])
                        
                        print(f"✅ [{learning_content_count} learning/{crawled_count} total] Saved: {page_data['title'][:50]}... ({len(page_data['content'])} chars)")
                        
                        # Add new links to queue (filter to avoid infinite loops)
                        for link in page_data['links']:
                            if link not in visited_urls and len(url_queue) < 2000:
                                # Enhanced filtering for better content discovery
                                if not any(skip in link for skip in [
                                    '/security/', '/releases/', '/calendar/', '/feed.xml',
                                    'mailto:', 'tel:', 'javascript:', '.pdf', '.zip', '.exe',
                                    '/search?', '/login', '/register', '/logout', '/profile',
                                    'twitter.com', 'facebook.com', 'github.com', 'linkedin.com',
                                    '/tag/', '/tags/', '/category/', '/categories/',
                                    '/page/', '/archives/', '/sitemap'
                                ]):
                                    # Prioritize content pages using website-specific keywords
                                    if any(keyword in link for keyword in website_config['priority_keywords']):
                                        url_queue.appendleft(link)  # Add to front for priority
                                    else:
                                        url_queue.append(link)  # Add to back for regular crawling
                    else:
                        print(f"❌ [{crawled_count}] Skipped non-educational: {page_data['title'][:50]}...")
                
                # Rate limiting
                await asyncio.sleep(2)  # Slightly longer delay for AI processing
            
            crawl_end_time = time.time()
            total_crawl_time = crawl_end_time - crawl_start_time
            
            print(f"\n✅ {website_config['name']} crawling completed!")
            print(f"📊 Total pages crawled: {crawled_count}")
            print(f"📚 Educational content found: {learning_content_count}")
            print(f"⏱️ Total crawling time: {total_crawl_time:.2f} seconds ({total_crawl_time/60:.1f} minutes)")
            print(f"🤖 AI classification time: {ai_classification_time:.2f} seconds")
            print(f"📈 Average time per page: {total_crawl_time/max(crawled_count,1):.2f} seconds")
            
        finally:
            await browser.close()

async def crawl_all_websites():
    """Crawl all configured websites"""
    total_crawl_start = time.time()
    print("🌐 Starting comprehensive multi-website crawling with AI content filtering...")
    
    for website in websites:
        await crawl_website(website)
        print("\n" + "="*80 + "\n")
    
    total_crawl_end = time.time()
    total_crawl_time = total_crawl_end - total_crawl_start
    print(f"🏁 All websites crawling completed!")
    print(f"⏱️ Total multi-website crawling time: {total_crawl_time:.2f} seconds ({total_crawl_time/60:.1f} minutes)")

def main():
    """Main function to run the async crawler for all websites"""
    print("🌐 Starting automatic website discovery and crawling...")
    asyncio.run(crawl_all_websites())
if __name__ == "__main__":
    main()