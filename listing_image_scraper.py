#!/usr/bin/env python3
"""
Listing Image Scraper

This script scrapes images from eBay and Swappa listings.
It can process a single URL or multiple URLs, creating separate folders for each listing.
Images are named based on the item title from the listing and saved in JPEG format.

Usage:
    ./listing_image_scraper.py --url URL [URL ...]
    ./listing_image_scraper.py --file FILE_WITH_URLS
"""

import argparse
import os
import re
import json
import sys
import signal
import logging
from urllib.parse import urlparse, urljoin
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
from PIL import Image
import io
import time
import random
from concurrent.futures import ThreadPoolExecutor
import string

### Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('listing_scraper.log')
    ]
)
logger = logging.getLogger(__name__)

### Global variables for statistics
stats = {
    'successful_listings': 0,
    'failed_listings': 0,
    'successful_images': 0,
    'failed_images': 0
}

### User agents to rotate through to avoid being blocked
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:95.0) Gecko/20100101 Firefox/95.0'
]

class UserAgentMiddleware:
    """Middleware to handle user agent rotation."""
    def __init__(self, user_agents):
        self.user_agents = user_agents

    def get_headers(self, referer=None):
        headers = {
            'User-Agent': random.choice(self.user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
        if referer:
            headers['Referer'] = referer
        return headers

def get_session():
    """Create a requests session with retry logic."""
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"]
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

# Initialize the user agent middleware
ua_middleware = UserAgentMiddleware(USER_AGENTS)

def sanitize_filename(name):
    """
    Sanitize the filename by removing invalid characters and limiting length.

    Args:
        name (str): The original filename

    Returns:
        str: Sanitized filename
    """
    # Remove invalid characters
    valid_chars = "-_.() %s%s" % (string.ascii_letters, string.digits)
    sanitized = ''.join(c for c in name if c in valid_chars)

    # Replace spaces with underscores
    sanitized = sanitized.replace(' ', '_')

    # Limit length to avoid path too long errors
    if len(sanitized) > 100:
        sanitized = sanitized[:97] + '...'

    return sanitized

def create_folder(folder_name):
    """
    Create a folder for the listing if it doesn't exist.

    Args:
        folder_name (str): Name of the folder to create

    Returns:
        str: Path to the created folder
    """
    # Sanitize folder name
    folder_name = sanitize_filename(folder_name)

    # Create base output directory if it doesn't exist
    base_dir = os.path.join(os.path.expanduser('~'), 'listing_images')
    if not os.path.exists(base_dir):
        os.makedirs(base_dir)

    # Create folder for this listing
    folder_path = os.path.join(base_dir, folder_name)
    os.makedirs(folder_path, exist_ok=True)

    return folder_path

def normalize_image_url(url):
    """
    Normalize image URLs to better detect duplicates.

    Args:
        url (str): The image URL

    Returns:
        str: Normalized URL
    """
    # Remove size parameters that don't affect the image content
    url = re.sub(r's-l\d+', 's-l1600', url)
    # Remove tracking parameters
    url = re.sub(r'\?.*$', '', url)
    return url

def download_image(url, folder_path, filename, index):
    """
    Download an image from the URL and save it to the specified folder.

    Args:
        url (str): URL of the image
        folder_path (str): Path to save the image
        filename (str): Base filename for the image
        index (int): Index of the image for the filename

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Add random delay with jitter to avoid detection patterns
        time.sleep(random.uniform(1.0, 3.0))

        headers = ua_middleware.get_headers(referer=url)
        headers['Accept'] = 'image/webp,image/apng,image/*,*/*;q=0.8'

        # Create a session with retry logic
        session = get_session()

        # Stream the image to avoid loading large images into memory
        response = session.get(url, headers=headers, stream=True, timeout=15)
        response.raise_for_status()

        # Check content type to ensure it's an image
        content_type = response.headers.get('Content-Type', '')
        if not content_type.startswith('image/'):
            logger.warning(f"URL doesn't return an image: {url}, content-type: {content_type}")
            stats['failed_images'] += 1
            return False

        # Determine file extension from content type or URL
        if 'image/jpeg' in content_type or 'image/jpg' in content_type:
            ext = '.jpg'
        elif 'image/png' in content_type:
            ext = '.png'
        elif 'image/webp' in content_type:
            ext = '.webp'
        elif 'image/gif' in content_type:
            ext = '.gif'
        else:
            # Default to jpg if can't determine
            ext = '.jpg'

        # Create full filename
        full_filename = f"{filename}_{index}{ext}"
        file_path = os.path.join(folder_path, full_filename)

        # Check if file already exists
        if os.path.exists(file_path):
            logger.info(f"Image already exists: {file_path}")
            return True

        # Save the image
        with open(file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        # If not jpg, convert to jpg
        if ext != '.jpg':
            try:
                img = Image.open(file_path)
                # Convert to RGB if needed (for PNG with transparency)
                if img.mode in ('RGBA', 'LA', 'P'):
                    img = img.convert('RGB')
                jpg_path = os.path.join(folder_path, f"{filename}_{index}.jpg")
                img.save(jpg_path, 'JPEG', quality=95)
                # Remove original file
                os.remove(file_path)
                file_path = jpg_path
            except Exception as e:
                logger.warning(f"Failed to convert image to JPG: {e}")

        logger.info(f"Downloaded image: {file_path}")
        stats['successful_images'] += 1
        return True

    except Exception as e:
        logger.error(f"Failed to download image {url}: {e}")
        stats['failed_images'] += 1
        return False

def scrape_ebay_listing(url):
    """
    Scrape images from an eBay listing.

    Args:
        url (str): URL of the eBay listing

    Returns:
        tuple: (title, list of image URLs)
    """
    try:
        session = get_session()
        headers = ua_middleware.get_headers()

        response = session.get(url, headers=headers, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')

        # Extract title
        title_elem = soup.select_one('h1.x-item-title__mainTitle span')
        if title_elem:
            title = title_elem.text.strip()
        else:
            # Try alternative title selectors
            title_elem = soup.select_one('title')
            if title_elem:
                title = title_elem.text.split('|')[0].strip()
            else:
                title = f"eBay_Item_{int(time.time())}"

        # Extract images
        image_urls = []

        # Method 1: Look for image URLs in script tags using direct pattern matching
        script_tags = soup.find_all('script', type='text/javascript')
        for script in script_tags:
            if script.string and 'imageUrl' in script.string:
                # Direct pattern matching for image URLs
                urls = re.findall(r'"imageUrl"\s*:\s*"([^"]+)"', script.string)
                image_urls.extend(urls)

        # Method 2: Look for image gallery
        if not image_urls:
            img_elements = soup.select('div.ux-image-carousel-item img')
            for img in img_elements:
                src = img.get('src', '')
                if src:
                    # Convert to full-size image URL if it's a thumbnail
                    src = src.replace('s-l64', 's-l1600').replace('s-l300', 's-l1600').replace('s-l400', 's-l1600')
                    image_urls.append(src)

        # Method 3: Look for meta og:image
        if not image_urls:
            meta_og_image = soup.select_one('meta[property="og:image"]')
            if meta_og_image and meta_og_image.get('content'):
                image_urls.append(meta_og_image.get('content'))

        # Method 4: Look for any image in the main content area
        if not image_urls:
            content_area = soup.select_one('div#vi_main_img_fs')
            if content_area:
                img_elements = content_area.select('img')
                for img in img_elements:
                    src = img.get('src', '')
                    if src:
                        image_urls.append(src)

        # Normalize and deduplicate image URLs
        normalized_urls = {}
        for url in image_urls:
            norm_url = normalize_image_url(url)
            if norm_url not in normalized_urls:
                normalized_urls[norm_url] = url

        image_urls = list(normalized_urls.values())

        return title, image_urls

    except Exception as e:
        logger.error(f"Failed to scrape eBay listing {url}: {e}")
        return None, []

def scrape_swappa_listing(url):
    """
    Scrape images from a Swappa listing.

    Args:
        url (str): URL of the Swappa listing

    Returns:
        tuple: (title, list of image URLs)
    """
    try:
        session = get_session()
        headers = ua_middleware.get_headers()

        response = session.get(url, headers=headers, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')

        # Extract title
        title_elem = soup.select_one('h1.listing_title')
        if title_elem:
            title = title_elem.text.strip()
        else:
            # Try alternative title selectors
            title_elem = soup.select_one('title')
            if title_elem:
                title = title_elem.text.split('|')[0].strip()
            else:
                title = f"Swappa_Item_{int(time.time())}"

        # Extract images
        image_urls = []

        # Method 1: Look for product gallery images
        img_elements = soup.select('img.product-gallery__slide-image')
        for img in img_elements:
            src = img.get('src', '')
            if src:
                image_urls.append(src)

        # Method 2: Look for data-src attributes (lazy loading)
        if not image_urls:
            img_elements = soup.select('img[data-src]')
            for img in img_elements:
                src = img.get('data-src', '')
                if src and ('product' in src.lower() or 'listing' in src.lower()):
                    image_urls.append(src)

        # Method 3: Look for meta og:image
        if not image_urls:
            meta_og_image = soup.select_one('meta[property="og:image"]')
            if meta_og_image and meta_og_image.get('content'):
                image_urls.append(meta_og_image.get('content'))

        # Method 4: Look for any images in the main content area
        if not image_urls:
            content_area = soup.select_one('div.listing_content')
            if content_area:
                img_elements = content_area.select('img')
                for img in img_elements:
                    src = img.get('src', '')
                    if src:
                        image_urls.append(src)

        # Normalize and deduplicate image URLs
        normalized_urls = {}
        for url in image_urls:
            norm_url = normalize_image_url(url)
            if norm_url not in normalized_urls:
                normalized_urls[norm_url] = url

        image_urls = list(normalized_urls.values())

        # Make sure all URLs are absolute
        base_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
        image_urls = [urljoin(base_url, img_url) for img_url in image_urls]

        return title, image_urls

    except Exception as e:
        logger.error(f"Failed to scrape Swappa listing {url}: {e}")
        return None, []

def process_listing(url):
    """
    Process a single listing URL.

    Args:
        url (str): URL of the listing

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        logger.info(f"Processing listing: {url}")

        # Determine the site
        domain = urlparse(url).netloc.lower()

        if 'ebay' in domain:
            title, image_urls = scrape_ebay_listing(url)
        elif 'swappa' in domain:
            title, image_urls = scrape_swappa_listing(url)
        else:
            logger.error(f"Unsupported site: {domain}")
            stats['failed_listings'] += 1
            return False

        if not title or not image_urls:
            logger.error(f"Failed to extract title or images from {url}")
            stats['failed_listings'] += 1
            return False

        # Create folder for this listing
        folder_path = create_folder(title)

        # Save listing URL to a text file in the folder
        with open(os.path.join(folder_path, 'source_url.txt'), 'w') as f:
            f.write(url)

        # Download images
        logger.info(f"Found {len(image_urls)} images for '{title}'")

        filename_base = sanitize_filename(title)

        for i, img_url in enumerate(image_urls):
            download_image(img_url, folder_path, filename_base, i+1)

        logger.info(f"Completed processing listing: {url}")
        stats['successful_listings'] += 1
        return True

    except Exception as e:
        logger.error(f"Error processing listing {url}: {e}")
        stats['failed_listings'] += 1
        return False

def signal_handler(sig, frame):
    """Handle keyboard interrupt by printing statistics before exiting."""
    print("\nInterrupted by user. Summary:")
    print_stats()
    sys.exit(0)

def print_stats():
    """Print the statistics of the scraping process."""
    print("\n=== Scraping Statistics ===")
    print(f"Successful listings: {stats['successful_listings']}")
    print(f"Failed listings: {stats['failed_listings']}")
    print(f"Successful images: {stats['successful_images']}")
    print(f"Failed images: {stats['failed_images']}")
    print("==========================\n")

def main():
    """Main function to parse arguments and process listings."""
    parser = argparse.ArgumentParser(description='Scrape images from eBay and Swappa listings.')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--url', nargs='+', help='One or more listing URLs to scrape')
    group.add_argument('--file', help='File containing listing URLs (one per line)')
    parser.add_argument('--threads', type=int, default=3, help='Number of concurrent threads (default: 3)')

    args = parser.parse_args()

    # Register signal handler for CTRL+C
    signal.signal(signal.SIGINT, signal_handler)

    urls = []

    if args.url:
        urls = args.url
    elif args.file:
        try:
            with open(args.file, 'r') as f:
                urls = [line.strip() for line in f if line.strip()]
        except Exception as e:
            logger.error(f"Failed to read URLs from file {args.file}: {e}")
            sys.exit(1)

    if not urls:
        logger.error("No URLs provided")
        sys.exit(1)

    logger.info(f"Starting to process {len(urls)} listings")

    # Process URLs in parallel
    with ThreadPoolExecutor(max_workers=args.threads) as executor:
        executor.map(process_listing, urls)

    print_stats()
    logger.info("Scraping completed")

if __name__ == "__main__":
    main()