import os
import requests
from bs4 import BeautifulSoup

PROFILE_URL = "https://hotpic.cc/u/deadpoet904"
BASE_URL = "https://hotpic.cc"
SEEN_FILE = "seen_albums.txt"
DOWNLOAD_DIR = "downloads"

def load_seen():
    """Load previously scraped album IDs to avoid duplicates."""
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return set(f.read().splitlines())
    return set()

def save_seen(seen):
    """Save the updated list of scraped album IDs."""
    with open(SEEN_FILE, "w") as f:
        f.write("\n".join(seen))

# 1. Added 'headers' parameter to bypass CDN blocking
def download_file(url, folder, headers):
    """Download the media file from the given URL."""
    if not url: return
    
    # Clean up the filename in case the CDN appends query parameters (e.g., .jpg?v=123)
    filename = url.split("/")[-1].split("?")[0]
    filepath = os.path.join(folder, filename)
    
    if not os.path.exists(filepath):
        print(f"Downloading: {filename}")
        try:
            # Pass the headers into the get request here!
            r = requests.get(url, stream=True, headers=headers, timeout=15)
            r.raise_for_status()
            with open(filepath, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        except Exception as e:
            print(f"Failed to download {url}: {e}")

def main():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    seen = load_seen()
    new_seen = seen.copy()

    # Added 'Referer' header. CDNs often check this to ensure requests are coming from the actual website.
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
        'Referer': f"{BASE_URL}/"
    }

    print(f"Checking profile: {PROFILE_URL}")
    try:
        r = requests.get(PROFILE_URL, headers=headers, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"Error fetching profile: {e}")
        return

    soup = BeautifulSoup(r.text, 'html.parser')
    
    # Find all a tags
    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href']
        
        # Look for album links
        if href.startswith('/album/'):
            album_id = href.split('/')[-1]
            if album_id in seen:
                continue 

            album_url = BASE_URL + href
            print(f"New album found: {album_url}")
            
            try:
                ar = requests.get(album_url, headers=headers, timeout=10)
                ar.raise_for_status()
            except:
                continue

            asoup = BeautifulSoup(ar.text, 'html.parser')
            
            # 2. Track processed items to avoid downloading the same image twice (via duplicate/nav links)
            processed_items = set()
            
            # Find item links inside the album
            for ia_tag in asoup.find_all('a', href=True):
                ihref = ia_tag['href']
                
                if '/i/' in ihref:
                    item_url = ihref if ihref.startswith('http') else BASE_URL + ihref
                    
                    if item_url in processed_items:
                        continue
                    processed_items.add(item_url)
                    
                    # 1. Check for Video thumbnail in the album page
                    video_tag = ia_tag.find('video')
                    if video_tag and video_tag.get('src'):
                        download_file(video_tag['src'], DOWNLOAD_DIR, headers)
                    else:
                        # 2. It's an image, we need to visit the item page
                        try:
                            ir = requests.get(item_url, headers=headers, timeout=10)
                            ir.raise_for_status()
                            isoup = BeautifulSoup(ir.text, 'html.parser')
                            
                            # Find the main image
                            img_tag = isoup.find('img', id='main-image')
                            if img_tag and img_tag.get('src'):
                                download_file(img_tag['src'], DOWNLOAD_DIR, headers)
                        except Exception as e:
                            print(f"Error extracting image from {item_url}: {e}")
                            
            # Mark album as seen
            new_seen.add(album_id)

    save_seen(new_seen)
    print("Run complete.")

if __name__ == "__main__":
    main()
