#!/usr/bin/env python3
"""
Streamlit-based Listing Image Scraper UI

A Streamlit-based UI for the listing_image_scraper.py script with extremely obvious progress indicators.
This UI focuses on making progress indicators very visible and ensuring they update properly during the scraping process.

Features:
1. Large, colored text panels showing the current status
2. Animated/pulsing elements to show active processing
3. Prominent progress bars that update in real-time
4. Clear counters showing images downloaded/total
5. A section showing which URL is currently being processed

Usage:
    streamlit run listing_image_scraper_ui.py
"""

import os
import sys
import time
import re
import threading
import tempfile
import importlib.util
import logging
from io import StringIO
from pathlib import Path
import streamlit as st
import pandas as pd
from datetime import datetime
import base64

# Configure page settings
st.set_page_config(
    page_title="Listing Image Scraper",
    page_icon="🖼️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for animated elements and styling
st.markdown("""
<style>
    /* Pulsating animation for active elements */
    @keyframes pulse {
        0% { opacity: 1; }
        50% { opacity: 0.5; }
        100% { opacity: 1; }
    }
    
    .pulse {
        animation: pulse 1.5s infinite ease-in-out;
    }
    
    /* Spinner animation */
    @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
    
    .spinner {
        display: inline-block;
        width: 20px;
        height: 20px;
        border: 5px solid rgba(255,255,255,.3);
        border-radius: 50%;
        border-top-color: #fff;
        animation: spin 1s ease-in-out infinite;
        margin-right: 10px;
    }
    
    /* Status containers */
    .status-container {
        padding: 15px;
        border-radius: 5px;
        margin-bottom: 15px;
        font-weight: bold;
    }
    
    .status-active {
        background-color: #0068c9;
        color: white;
    }
    
    .status-success {
        background-color: #09ab3b;
        color: white;
    }
    
    .status-warning {
        background-color: #ffbb00;
        color: black;
    }
    
    .status-error {
        background-color: #ff4b4b;
        color: white;
    }
    
    .status-info {
        background-color: #262730;
        color: white;
    }
    
    /* Current URL container */
    .current-url {
        padding: 10px;
        background-color: #262730;
        color: #fafafa;
        border-radius: 5px;
        overflow-wrap: break-word;
        word-wrap: break-word;
        word-break: break-all;
    }
    
    /* Large counter */
    .large-counter {
        font-size: 2.5rem;
        font-weight: bold;
        text-align: center;
    }
    
    /* Highlight text */
    .highlight {
        background-color: yellow;
        color: black;
        padding: 2px 5px;
        border-radius: 3px;
    }
    
    /* Progress bar customization */
    .stProgress > div > div > div > div {
        background-color: #0068c9;
    }
</style>
""", unsafe_allow_html=True)

# Import the listing_image_scraper module from the current directory
script_dir = os.path.dirname(os.path.abspath(__file__))
script_path = os.path.join(script_dir, 'listing_image_scraper.py')
spec = importlib.util.spec_from_file_location("listing_image_scraper", script_path)
listing_scraper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(listing_scraper)

# Configure logging to capture output
log_stream = StringIO()
log_handler = logging.StreamHandler(log_stream)
log_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
listing_scraper.logger.addHandler(log_handler)

# Initialize session state if not already done
if 'initialized' not in st.session_state:
    st.session_state.initialized = True
    st.session_state.scraping_in_progress = False
    st.session_state.scraping_complete = False
    st.session_state.progress = 0
    st.session_state.total_urls = 0
    st.session_state.processed_urls = 0
    st.session_state.current_url = None
    st.session_state.current_title = None
    st.session_state.current_images_found = 0
    st.session_state.current_images_downloaded = 0
    st.session_state.start_time = None
    st.session_state.stats = {
        'successful_listings': 0,
        'failed_listings': 0,
        'successful_images': 0,
        'failed_images': 0
    }
    st.session_state.processed_listings = []
    st.session_state.log_messages = []

def add_log_message(message, level="INFO"):
    """Add a log message to the session state"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    st.session_state.log_messages.append({
        "timestamp": timestamp,
        "level": level,
        "message": message
    })

def validate_urls(urls):
    """
    Validate a list of URLs to ensure they are from supported sites.
    
    Args:
        urls (list): List of URLs to validate
        
    Returns:
        tuple: (valid_urls, invalid_urls)
    """
    valid_urls = []
    invalid_urls = []
    
    for url in urls:
        url = url.strip()
        if not url:
            continue
            
        # Basic URL validation
        if not re.match(r'^https?://', url):
            invalid_urls.append(f"{url} - Invalid URL format")
            continue
            
        # Check if it's from a supported site
        if 'ebay' not in url.lower() and 'swappa' not in url.lower():
            invalid_urls.append(f"{url} - Unsupported site (only eBay and Swappa are supported)")
            continue
            
        valid_urls.append(url)
    
    return valid_urls, invalid_urls

# Override the download_image function to track per-image progress
original_download_image = listing_scraper.download_image

def custom_download_image(url, folder_path, filename, index):
    """Custom download_image function that updates the UI with per-image progress"""
    try:
        add_log_message(f"Downloading image {index} from {url}")
        result = original_download_image(url, folder_path, filename, index)
        if result:
            st.session_state.current_images_downloaded += 1
            st.session_state.stats['successful_images'] += 1
            add_log_message(f"Successfully downloaded image {index}", "SUCCESS")
        else:
            st.session_state.stats['failed_images'] += 1
            add_log_message(f"Failed to download image {index} from {url}", "ERROR")
        return result
    except Exception as e:
        st.session_state.stats['failed_images'] += 1
        add_log_message(f"Error downloading image {index}: {str(e)}", "ERROR")
        return False

listing_scraper.download_image = custom_download_image

# Override the process_listing function to track per-listing progress
original_process_listing = listing_scraper.process_listing

def custom_process_listing(url):
    """Custom process_listing function that updates the UI with per-listing progress"""
    try:
        add_log_message(f"Processing URL: {url}")
        
        st.session_state.current_url = url
        st.session_state.current_title = None
        st.session_state.current_images_found = 0
        st.session_state.current_images_downloaded = 0
        
        # Determine the site
        domain = listing_scraper.urlparse(url).netloc.lower()
        
        if 'ebay' in domain:
            add_log_message(f"Detected eBay listing: {url}")
            title, image_urls = listing_scraper.scrape_ebay_listing(url)
        elif 'swappa' in domain:
            add_log_message(f"Detected Swappa listing: {url}")
            title, image_urls = listing_scraper.scrape_swappa_listing(url)
        else:
            add_log_message(f"Unsupported site: {domain}", "ERROR")
            listing_scraper.stats['failed_listings'] += 1
            st.session_state.stats['failed_listings'] += 1
            
            # Add to processed listings
            st.session_state.processed_listings.append({
                'url': url,
                'title': None,
                'status': 'failed',
                'images_found': 0,
                'images_downloaded': 0,
                'error': f"Unsupported site: {domain}"
            })
            
            return False
        
        st.session_state.current_title = title
        
        if not title or not image_urls:
            add_log_message(f"Failed to extract title or images from {url}", "ERROR")
            listing_scraper.stats['failed_listings'] += 1
            st.session_state.stats['failed_listings'] += 1
            
            # Add to processed listings
            st.session_state.processed_listings.append({
                'url': url,
                'title': title,
                'status': 'failed',
                'images_found': 0,
                'images_downloaded': 0,
                'error': "Failed to extract title or images"
            })
            
            return False
        
        # Create folder for this listing
        folder_path = listing_scraper.create_folder(title)
        
        # Save listing URL to a text file in the folder
        with open(os.path.join(folder_path, 'source_url.txt'), 'w') as f:
            f.write(url)
        
        # Update images found
        st.session_state.current_images_found = len(image_urls)
        
        add_log_message(f"Found {len(image_urls)} images for '{title}'", "SUCCESS")
        
        # Download images
        listing_scraper.logger.info(f"Found {len(image_urls)} images for '{title}'")
        
        filename_base = listing_scraper.sanitize_filename(title)
        
        for i, img_url in enumerate(image_urls):
            add_log_message(f"Downloading image {i+1}/{len(image_urls)}")
            listing_scraper.download_image(img_url, folder_path, filename_base, i+1)
        
        add_log_message(f"Completed listing: {url}", "SUCCESS")
        listing_scraper.stats['successful_listings'] += 1
        st.session_state.stats['successful_listings'] += 1
        
        # Add to processed listings
        st.session_state.processed_listings.append({
            'url': url,
            'title': title,
            'status': 'completed',
            'images_found': len(image_urls),
            'images_downloaded': st.session_state.current_images_downloaded,
            'error': None
        })
        
        return True
    
    except Exception as e:
        add_log_message(f"Error processing listing {url}: {str(e)}", "ERROR")
        listing_scraper.stats['failed_listings'] += 1
        st.session_state.stats['failed_listings'] += 1
        
        # Add to processed listings
        st.session_state.processed_listings.append({
            'url': url,
            'title': st.session_state.current_title,
            'status': 'failed',
            'images_found': st.session_state.current_images_found,
            'images_downloaded': st.session_state.current_images_downloaded,
            'error': str(e)
        })
        
        return False

listing_scraper.process_listing = custom_process_listing

def process_urls_thread(urls, output_dir=None):
    """
    Process a list of URLs in a separate thread.
    
    Args:
        urls (list): List of URLs to process
        output_dir (str, optional): Custom output directory
    """
    # Reset stats
    listing_scraper.stats = {
        'successful_listings': 0,
        'failed_listings': 0,
        'successful_images': 0,
        'failed_images': 0
    }
    
    # Set custom output directory if specified
    if output_dir:
        # Temporarily modify the create_folder function to use the custom output directory
        original_create_folder = listing_scraper.create_folder
        
        def custom_create_folder(folder_name):
            # Sanitize folder name
            folder_name = listing_scraper.sanitize_filename(folder_name)
            
            # Create folder for this listing
            folder_path = os.path.join(output_dir, folder_name)
            os.makedirs(folder_path, exist_ok=True)
            
            return folder_path
        
        listing_scraper.create_folder = custom_create_folder
    
    st.session_state.total_urls = len(urls)
    st.session_state.processed_urls = 0
    st.session_state.scraping_in_progress = True
    st.session_state.scraping_complete = False
    st.session_state.progress = 0
    st.session_state.start_time = time.time()
    st.session_state.processed_listings = []
    
    add_log_message(f"Starting scrape of {len(urls)} URLs", "INFO")
    
    try:
        # Process each URL with progress tracking
        for url in urls:
            # Process the URL
            listing_scraper.process_listing(url)
            
            # Update progress
            st.session_state.processed_urls += 1
            st.session_state.progress = st.session_state.processed_urls / st.session_state.total_urls
            
            # Log summary after each URL
            elapsed = time.time() - st.session_state.start_time
            add_log_message(f"Processed {st.session_state.processed_urls}/{st.session_state.total_urls} URLs in {elapsed:.1f} seconds")
        
        # Restore original create_folder function if it was modified
        if output_dir:
            listing_scraper.create_folder = original_create_folder
        
        st.session_state.scraping_complete = True
        add_log_message("Scraping completed successfully!", "SUCCESS")
    except Exception as e:
        add_log_message(f"Error during scraping: {str(e)}", "ERROR")
    finally:
        st.session_state.scraping_in_progress = False
        
        # Log final statistics
        add_log_message("Final Statistics:", "INFO")
        add_log_message(f"Total URLs processed: {st.session_state.processed_urls}/{st.session_state.total_urls}")
        add_log_message(f"Successful listings: {st.session_state.stats['successful_listings']}")
        add_log_message(f"Failed listings: {st.session_state.stats['failed_listings']}")
        add_log_message(f"Successful images: {st.session_state.stats['successful_images']}")
        add_log_message(f"Failed images: {st.session_state.stats['failed_images']}")
        
        # Log output directory
        output_path = output_dir if output_dir else os.path.join(os.path.expanduser('~'), 'listing_images')
        add_log_message(f"Images saved to: {output_path}")

def start_scraping(urls, output_dir=None):
    """Start the scraping process in a separate thread"""
    if st.session_state.scraping_in_progress:
        st.warning("Scraping is already in progress!")
        return
    
    # Clear previous log messages
    st.session_state.log_messages = []
    
    # Start the scraping thread
    thread = threading.Thread(target=process_urls_thread, args=(urls, output_dir))
    thread.daemon = True
    thread.start()

def read_urls_from_file(file):
    """Read URLs from an uploaded file"""
    try:
        content = file.getvalue().decode("utf-8")
        return [line.strip() for line in content.split('\n') if line.strip()]
    except Exception as e:
        st.error(f"Failed to read URLs from file: {str(e)}")
        return []

def get_elapsed_time():
    """Get the elapsed time since the start of scraping"""
    if st.session_state.start_time:
        elapsed = time.time() - st.session_state.start_time
        minutes, seconds = divmod(int(elapsed), 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return "00:00:00"

def main():
    """Main Streamlit UI function"""
    st.title("🖼️ Listing Image Scraper")
    st.markdown("Download images from eBay and Swappa listings with real-time progress tracking")
    
    # Sidebar for input options
    st.sidebar.header("Input Options")
    
    input_method = st.sidebar.radio("Select input method:", ["Enter URLs", "Upload File"])
    
    urls = []
    
    if input_method == "Enter URLs":
        url_input = st.sidebar.text_area("Enter URLs (one per line):", height=150)
        if url_input:
            urls = [line.strip() for line in url_input.split('\n') if line.strip()]
    else:
        uploaded_file = st.sidebar.file_uploader("Upload a file with URLs (one per line)", type=["txt"])
        if uploaded_file:
            urls = read_urls_from_file(uploaded_file)
    
    # Output directory option
    output_dir = st.sidebar.text_input("Custom output directory (optional):", "")
    if output_dir and not os.path.exists(output_dir):
        st.sidebar.warning(f"Directory does not exist: {output_dir}")
        if st.sidebar.button("Create directory"):
            try:
                os.makedirs(output_dir, exist_ok=True)
                st.sidebar.success(f"Created directory: {output_dir}")
            except Exception as e:
                st.sidebar.error(f"Failed to create directory: {str(e)}")
    
    # Validate URLs
    valid_urls = []
    invalid_urls = []
    
    if urls:
        valid_urls, invalid_urls = validate_urls(urls)
        
        st.sidebar.markdown(f"**Found {len(valid_urls)} valid URLs**")
        
        if invalid_urls:
            with st.sidebar.expander(f"⚠️ {len(invalid_urls)} invalid URLs"):
                for invalid_url in invalid_urls:
                    st.markdown(f"- {invalid_url}")
    
    # Start scraping button
    if valid_urls:
        if st.sidebar.button("Start Scraping", type="primary", disabled=st.session_state.scraping_in_progress):
            start_scraping(valid_urls, output_dir if output_dir else None)
    
    # Main content area - Status and progress indicators
    col1, col2 = st.columns([2, 1])
    
    with col1:
        # Status indicator
        if st.session_state.scraping_in_progress:
            st.markdown("""
            <div class="status-container status-active pulse">
                <div class="spinner"></div>
                SCRAPING IN PROGRESS...
            </div>
            """, unsafe_allow_html=True)
        elif st.session_state.scraping_complete:
            st.markdown("""
            <div class="status-container status-success">
                ✅ SCRAPING COMPLETED SUCCESSFULLY!
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown("""
            <div class="status-container status-info">
                READY TO START SCRAPING
            </div>
            """, unsafe_allow_html=True)
        
        # Current URL being processed
        if st.session_state.scraping_in_progress and st.session_state.current_url:
            st.markdown("### 🔄 Currently Processing")
            st.markdown(f"""
            <div class="current-url pulse">
                {st.session_state.current_url}
            </div>
            """, unsafe_allow_html=True)
            
            if st.session_state.current_title:
                st.markdown(f"**Title:** {st.session_state.current_title}")
    
    with col2:
        # Elapsed time
        st.markdown("### ⏱️ Elapsed Time")
        st.markdown(f"""
        <div class="large-counter">
            {get_elapsed_time()}
        </div>
        """, unsafe_allow_html=True)
        
        # Overall progress
        st.markdown("### 📊 Overall Progress")
        st.progress(st.session_state.progress)
        st.markdown(f"""
        <div style="text-align: center; font-weight: bold;">
            {st.session_state.processed_urls} / {st.session_state.total_urls} URLs
        </div>
        """, unsafe_allow_html=True)
    
    # Image download progress
    if st.session_state.scraping_in_progress and st.session_state.current_images_found > 0:
        st.markdown("### 📷 Current Listing Progress")
        image_progress = st.session_state.current_images_downloaded / st.session_state.current_images_found
        
        # Create a progress bar that pulses when active
        progress_bar = st.progress(image_progress)
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.markdown(f"""
            <div class="status-container status-info" style="text-align: center;">
                <span class="highlight">{st.session_state.current_images_downloaded}</span> / {st.session_state.current_images_found} Images
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown(f"""
            <div class="status-container status-success" style="text-align: center;">
                ✅ {st.session_state.stats['successful_images']} Images Downloaded
            </div>
            """, unsafe_allow_html=True)
        
        with col3:
            st.markdown(f"""
            <div class="status-container status-error" style="text-align: center;">
                ❌ {st.session_state.stats['failed_images']} Images Failed
            </div>
            """, unsafe_allow_html=True)
    
    # Statistics
    if st.session_state.scraping_in_progress or st.session_state.scraping_complete:
        st.markdown("### 📈 Statistics")
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("URLs Processed", f"{st.session_state.processed_urls}/{st.session_state.total_urls}")
        
        with col2:
            st.metric("Successful Listings", st.session_state.stats['successful_listings'])
        
        with col3:
            st.metric("Failed Listings", st.session_state.stats['failed_listings'])
        
        with col4:
            st.metric("Images Downloaded", st.session_state.stats['successful_images'])
    
    # Processed listings table
    if st.session_state.processed_listings:
        st.markdown("### 📋 Processed Listings")
        
        # Convert to DataFrame for display
        df = pd.DataFrame(st.session_state.processed_listings)
        
        # Format the status column
        def format_status(status):
            if status == 'completed':
                return '✅ Completed'
            else:
                return '❌ Failed'
        
        if not df.empty:
            df['status'] = df['status'].apply(format_status)
            
            # Reorder and rename columns
            df = df[['url', 'title', 'status', 'images_found', 'images_downloaded', 'error']]
            df.columns = ['URL', 'Title', 'Status', 'Images Found', 'Images Downloaded', 'Error']
            
            # Display the table
            st.dataframe(df, use_container_width=True)
    
    # Log messages
    with st.expander("📝 Log Messages", expanded=False):
        # Display log messages in a scrollable area
        log_df = pd.DataFrame(st.session_state.log_messages)
        if not log_df.empty:
            st.dataframe(log_df, use_container_width=True, height=300)
        else:
            st.info("No log messages yet.")

if __name__ == "__main__":
    main()
