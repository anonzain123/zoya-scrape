import os
import sys
import requests
from bs4 import BeautifulSoup

PROFILE_URL = "https://hotpic.cc/u/deadpoet904"
BASE_URL = "https://hotpic.cc"
SEEN_FILE = "seen_albums.txt"
DOWNLOAD_DIR = "downloads"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
    'Referer': f"{BASE_URL}/"
}

def load_seen():
    """Load previously scraped album IDs to avoid duplicates."""
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_seen(seen):
    """Save the updated list of scraped album IDs."""
    with open(SEEN_FILE, "w") as f:
        f.write("\n".join(sorted(seen)) + "\n")

def download_file(url, folder, headers):
    """Download the media file from the given URL. Returns True if successful, False otherwise."""
    if not url:
        return False

    filename = url.split("/")[-1].split("?")[0]
    filepath = os.path.join(folder, filename)

    if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
        print(f"Skipping (already exists): {filename}")
        return True

    print(f"Downloading: {filename}")
    try:
        r = requests.get(url, stream=True, headers=headers, timeout=20)
        r.raise_for_status()
        with open(filepath, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"Failed to download {url}: {e}")
        # Clean up partial corrupted files if any
        if os.path.exists(filepath):
            os.remove(filepath)
        return False

def write_github_summary(new_albums_count, downloaded_count, failed_items):
    """Generate GitHub Actions Step Summary and UI annotations."""
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    summary_md = []
    summary_md.append("## 📸 Scraper Execution Summary\n")
    summary_md.append(f"* **New Albums Detected:** {new_albums_count}")
    summary_md.append(f"* **Files Downloaded Successfully:** {downloaded_count}")
    summary_md.append(f"* **Failed Files:** {len(failed_items)}\n")

    if failed_items:
        summary_md.append("### ⚠️ Failed Media (Will Retry Next Run)\n")
        summary_md.append("| Album URL | Media / Item URL | Reason |")
        summary_md.append("| :--- | :--- | :--- |")
        for album_url, media_url, reason in failed_items:
            summary_md.append(f"| [Album Link]({album_url}) | [Media Link]({media_url}) | `{reason}` |")
            # Print GitHub Annotation for immediate visual alert in the workflow UI
            print(f"::error title=Download Failed::{reason} -> {media_url} (Album: {album_url})")

    if summary_file:
        with open(summary_file, "a") as f:
            f.write("\n".join(summary_md) + "\n")

def main():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    seen = load_seen()
    new_seen = seen.copy()

    total_downloaded = 0
    new_albums_found = 0
    failed_items = []

    print(f"Checking profile: {PROFILE_URL}")
    try:
        r = requests.get(PROFILE_URL, headers=HEADERS, timeout=15)
        r.raise_for_status()
    except Exception as e:
        print(f"Error fetching profile: {e}")
        print(f"::error title=Profile Fetch Failed::{e}")
        sys.exit(1)

    soup = BeautifulSoup(r.text, 'html.parser')

    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href']

        if href.startswith('/album/'):
            album_id = href.split('/')[-1]
            if album_id in seen:
                continue

            new_albums_found += 1
            album_url = BASE_URL + href
            print(f"\n--- New album found: {album_url} ---")

            try:
                ar = requests.get(album_url, headers=HEADERS, timeout=15)
                ar.raise_for_status()
            except Exception as e:
                print(f"Failed to load album {album_url}: {e}")
                failed_items.append((album_url, album_url, f"Failed album HTTP fetch: {e}"))
                continue

            asoup = BeautifulSoup(ar.text, 'html.parser')
            processed_items = set()
            album_fully_successful = True
            items_found_in_album = 0

            for ia_tag in asoup.find_all('a', href=True):
                ihref = ia_tag['href']

                if '/i/' in ihref:
                    item_url = ihref if ihref.startswith('http') else BASE_URL + ihref

                    if item_url in processed_items:
                        continue
                    processed_items.add(item_url)
                    items_found_in_album += 1

                    # 1. Video check
                    video_tag = ia_tag.find('video')
                    if video_tag and video_tag.get('src'):
                        video_src = video_tag['src']
                        success = download_file(video_src, DOWNLOAD_DIR, HEADERS)
                        if success:
                            total_downloaded += 1
                        else:
                            album_fully_successful = False
                            failed_items.append((album_url, video_src, "Video file download failed"))
                    else:
                        # 2. Image check
                        try:
                            ir = requests.get(item_url, headers=HEADERS, timeout=15)
                            ir.raise_for_status()
                            isoup = BeautifulSoup(ir.text, 'html.parser')

                            img_tag = isoup.find('img', id='main-image')
                            if img_tag and img_tag.get('src'):
                                img_src = img_tag['src']
                                success = download_file(img_src, DOWNLOAD_DIR, HEADERS)
                                if success:
                                    total_downloaded += 1
                                else:
                                    album_fully_successful = False
                                    failed_items.append((album_url, img_src, "Image file download failed"))
                            else:
                                album_fully_successful = False
                                failed_items.append((album_url, item_url, "Could not find img#main-image on item page"))
                        except Exception as e:
                            album_fully_successful = False
                            failed_items.append((album_url, item_url, f"Failed parsing item page: {e}"))

            # ONLY mark album as seen if all items downloaded without errors
            if album_fully_successful and items_found_in_album > 0:
                print(f"Album {album_id} completed successfully.")
                new_seen.add(album_id)
            else:
                print(f"Album {album_id} had failures or was empty. Will be retried on next run.")

    # Save progress for any albums that completely succeeded
    if new_seen != seen:
        save_seen(new_seen)

    write_github_summary(new_albums_found, total_downloaded, failed_items)
    print("\nRun complete.")

    # Fail the GitHub step if any items failed so it shows up red in GitHub Actions
    if failed_items:
        print(f"\nCompleted with {len(failed_items)} failed download(s).")
        sys.exit(1)

if __name__ == "__main__":
    main()
