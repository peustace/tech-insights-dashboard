import os
import re
import json
import datetime
import feedparser
from youtube_transcript_api import YouTubeTranscriptApi
from google import genai

# Initialize Gemini API Client
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# High-Signal Source Matrix (Journals, arXiv, Tech Blogs, YouTube & Podcasts)
SOURCES = {
    "AI": {
        "text_feeds": [
            "http://export.arxiv.org/rss/cs.AI",
            "https://huggingface.co/blog/feed.xml"
        ],
        "youtube_videos": [
            "https://www.youtube.com/watch?v=kCc8FmEb1nY" # Example technical AI video URL
        ]
    },
    "Quantum": {
        "text_feeds": [
            "http://export.arxiv.org/rss/quant-ph",
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
        ],
        "podcasts": [
            "https://www.planetary.org/rss/planetary-radio"
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
    }
}

def extract_youtube_transcript(video_url):
    """Extracts raw caption transcript text from a YouTube video link."""
    try:
        video_id = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11})", video_url).group(1)
        ytt_api = YouTubeTranscriptApi()
        fetched = ytt_api.fetch(video_id, languages=['en'])
        transcript_text = " ".join([item.text for item in fetched])
        return transcript_text[:4000] # Limit tokens for fast processing
    except Exception as e:
        print(f"Skipping transcript for {video_url}: {e}")
        return None

def summarize_with_gemini(source_type, title, raw_content):
    """Uses Gemini 2.5 Flash to generate executive bullet points."""
    prompt = f"""
    You are an expert technology analyst.
    Summarize the following high-signal {source_type} for an executive dashboard.
    
    Title: {title}
    Source Material: {raw_content}
    
    Provide a concise 2-sentence key takeaway highlighting technical innovations, core results, or industry impact.
    Do not use introductory fluff. Jump straight to the point.
    """
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        return response.text.strip()
    except Exception as e:
        print(f"Gemini API Error: {e}")
        return raw_content[:200] + "..."

def generate_weekly_analysis(sectors_summary):
    """Generates the Sunday Weekly Recap and Stock Impact Radar."""
    prompt = f"""
    You are an executive technology and financial strategist.
    Based on this week's sector insights: {json.dumps(sectors_summary)}
    
    1. Write a 3-sentence high-level summary of the week's most critical technological shifts across AI, Quantum, Cyber, Space, Energy, and MedTech.
    2. Identify 3 publicly traded companies impacted by these developments and write a short blurb for each explaining how recent technical updates will influence their stock or positioning in time.
    
    Format output strictly as JSON with keys 'recap' and 'stock_watch'.
    Example format:
    {{
      "recap": "Summary string here...",
      "stock_watch": [
         {{"ticker": "NVDA", "company": "NVIDIA", "impact_blurb": "Impact statement..."}}
      ]
    }}
    """
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config={"response_mime_type": "application/json"}
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"Error generating weekly analysis: {e}")
        return {
            "recap": "Weekly analysis generated. Key technological strides observed in underlying papers and sector logs.",
            "stock_watch": []
        }

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

    # Fetch and process items across all sectors
    for sector, sources in SOURCES.items():
        sector_items = []
        
        # 1. Process YouTube Video Transcripts
        for vid_url in sources.get("youtube_videos", []):
            transcript = extract_youtube_transcript(vid_url)
            if transcript:
                summary = summarize_with_gemini("Video Transcript", "YouTube Insight", transcript)
                sector_items.append({
                    "title": "🎥 Technical Video Briefing",
                    "summary": summary,
                    "link": vid_url
                })

        # 2. Process Podcasts
        for pod_feed in sources.get("podcasts", []):
            feed = feedparser.parse(pod_feed)
            for entry in feed.entries[:2]:
                summary = summarize_with_gemini("Podcast Episode", entry.title, entry.summary)
                sector_items.append({
                    "title": f"🎙️ {entry.title}",
                    "summary": summary,
                    "link": entry.link
                })

        # 3. Process Academic Papers & Technical Blogs
        for feed_url in sources.get("text_feeds", []):
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:2]:
                raw_text = entry.get("summary", entry.get("description", ""))
                summary = summarize_with_gemini("Journal/Blog Entry", entry.title, raw_text)
                sector_items.append({
                    "title": f"📄 {entry.title}",
                    "summary": summary,
                    "link": entry.link
                })

        dashboard_data["sectors"][sector] = sector_items[:5]

    # Generate Sunday Special Analysis
    if is_sunday:
        sunday_analysis = generate_weekly_analysis(dashboard_data["sectors"])
        dashboard_data["weekly_recap"] = sunday_analysis.get("recap")
        dashboard_data["stock_watch"] = sunday_analysis.get("stock_watch", [])

    # Save output to data.json
    with open("data.json", "w") as f:
        json.dump(dashboard_data, f, indent=2)

if __name__ == "__main__":
    run_pipeline()
