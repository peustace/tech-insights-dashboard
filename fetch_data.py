import os
import re
import json
import datetime
import feedparser
from youtube_transcript_api import YouTubeTranscriptApi
from google import genai

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# High-Signal & Credible Sources
SOURCES = {
    "AI": {
        "text_feeds": [
            "https://rss.arxiv.org/rss/cs.AI",
            "https://huggingface.co/blog/feed.xml"
        ]
    },
    "Quantum": {
        "text_feeds": [
            "https://rss.arxiv.org/rss/quant-ph",
            "https://quantumcomputingreport.com/feed/"
        ]
    },
    "CyberSecurity": {
        "text_feeds": [
            "https://www.schneier.com/feed/atom/"
        ],
        "podcasts": [
            "https://feeds.feedburner.com/sans-isc-podcast"
        ]
    },
    "Space": {
        "text_feeds": [
            "https://spacenews.com/feed/"
        ]
    },
    "Renewables": {
        "text_feeds": [
            "https://cleantechnica.com/feed/",
            "https://www.volts.wtf/feed"
        ]
    },
    "Energy": {
        "text_feeds": [
            "https://www.carbonbrief.org/feed/",
            "https://www.energy-storage.news/feed/"
        ]
    },
    "MedTech": {
        "text_feeds": [
            "https://www.medtechdive.com/feeds/news/"
        ]
    },
    "Telecommunications": {
        "text_feeds": [
            "https://rss.arxiv.org/rss/cs.NI",
            "https://www.lightreading.com/rss.xml"
        ]
    },
    "Robotics": {
        "text_feeds": [
            "https://rss.arxiv.org/rss/cs.RO",
            "https://www.theroboticsreport.com/feed/"
        ]
    }
}

def clean_html(raw_html):
    """Strips all HTML tags (including <img>, <a>, <div>) to leave pure text."""
    clean_text = re.sub(r'<[^>]+>', '', raw_html)
    return clean_text.strip()

def extract_youtube_transcript(video_url):
    try:
        video_id = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11})", video_url).group(1)
        ytt_api = YouTubeTranscriptApi()
        fetched = ytt_api.fetch(video_id, languages=['en'])
        return " ".join([item.text for item in fetched])[:4000]
    except Exception as e:
        print(f"Skipping transcript for {video_url}: {e}")
        return None

def summarize_with_gemini(source_type, title, raw_content):
    prompt = f"""
    You are an expert technology analyst.
    Summarize the following high-signal {source_type} for an executive dashboard.
    
    Title: {title}
    Source Material: {raw_content}
    
    Provide a concise 2-sentence key takeaway highlighting technical innovations or industry impact.
    Do not include any introductory text or fluff.
    """
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        return clean_html(response.text.strip())
    except Exception as e:
        print(f"Gemini API Error: {e}")
        return clean_html(raw_content)[:200] + "..."

def generate_stock_analysis(sectors_summary):
    prompt = f"""
    You are an executive technology and financial strategist.
    Based on today's sector insights: {json.dumps(sectors_summary)}
    
    Identify 3 publicly traded companies directly or indirectly impacted by today's technical developments and write a short 2-sentence blurb for each explaining how recent sector updates will influence their stock or strategic positioning in time.
    
    Format output strictly as a JSON list of objects:
    [
      {{"ticker": "NVDA", "company": "NVIDIA", "impact_blurb": "Impact statement..."}}
    ]
    """
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config={"response_mime_type": "application/json"}
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"Error generating stock analysis: {e}")
        return []

def run_pipeline():
    now = datetime.datetime.now()
    is_sunday = now.weekday() == 6
    
    dashboard_data = {
        "last_updated": now.strftime("%Y-%m-%d %H:%M UTC"),
        "is_sunday_edition": is_sunday,
        "sectors": {},
        "weekly_recap": None,
        "stock_watch": []
    }

    for sector, sources in SOURCES.items():
        sector_items = []
        
        for vid_url in sources.get("youtube_videos", []):
            transcript = extract_youtube_transcript(vid_url)
            if transcript:
                summary = summarize_with_gemini("Video Transcript", "YouTube Insight", transcript)
                sector_items.append({
                    "title": "🎥 Technical Video Briefing",
                    "summary": summary,
                    "link": vid_url
                })

        for pod_feed in sources.get("podcasts", []):
            feed = feedparser.parse(pod_feed)
            for entry in feed.entries[:2]:
                cleaned_summary = clean_html(entry.get("summary", entry.get("description", "")))
                summary = summarize_with_gemini("Podcast Episode", entry.title, cleaned_summary)
                sector_items.append({
                    "title": f"🎙️ {entry.title}",
                    "summary": summary,
                    "link": entry.link
                })

        for feed_url in sources.get("text_feeds", []):
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:3]:
                cleaned_text = clean_html(entry.get("summary", entry.get("description", "")))
                summary = summarize_with_gemini("Journal/Blog Entry", entry.title, cleaned_text)
                sector_items.append({
                    "title": f"📄 {entry.title}",
                    "summary": summary,
                    "link": entry.link
                })

        dashboard_data["sectors"][sector] = sector_items[:5]

    dashboard_data["stock_watch"] = generate_stock_analysis(dashboard_data["sectors"])

    with open("data.json", "w") as f:
        json.dump(dashboard_data, f, indent=2)

if __name__ == "__main__":
    run_pipeline()
