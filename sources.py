"""Feed configuration for the Tech Insights Dashboard.

Each sector maps to a list of feeds. Per-feed options:
    url     (required) feed URL
    name    (required) short source name shown in the UI
    type    "news" | "paper" | "podcast" | "community"   (default "news")
    weight  ranking multiplier, 1.0 = normal              (default 1.0)
    limit   max entries read per run                      (default 4)

Feed health is reported on every run (see "health" in data.json and the footer
of the page), so a dead or renamed feed shows up instead of failing silently.
"""

# Sectors listed in PRIORITY_SECTORS get larger cards by default in the UI.
PRIORITY_SECTORS = ["AI", "Semiconductors", "CyberSecurity"]

SOURCES = {
    "AI": [
        {"name": "Hugging Face", "url": "https://huggingface.co/blog/feed.xml"},
        {"name": "Import AI", "url": "https://importai.substack.com/feed"},
        {"name": "arXiv cs.AI", "url": "https://rss.arxiv.org/rss/cs.AI", "type": "paper", "weight": 0.6, "limit": 3},
    ],
    "Semiconductors": [
        {"name": "SemiEngineering", "url": "https://semiengineering.com/feed/"},
        {"name": "EE Times", "url": "https://www.eetimes.com/feed/"},
    ],
    "Quantum": [
        {"name": "Quantum Computing Report", "url": "https://quantumcomputingreport.com/feed/"},
        {"name": "arXiv quant-ph", "url": "https://rss.arxiv.org/rss/quant-ph", "type": "paper", "weight": 0.6, "limit": 3},
    ],
    "CyberSecurity": [
        {"name": "Krebs on Security", "url": "https://krebsonsecurity.com/feed/"},
        {"name": "BleepingComputer", "url": "https://www.bleepingcomputer.com/feed/"},
        {"name": "Schneier on Security", "url": "https://www.schneier.com/feed/atom/"},
        {"name": "SANS ISC Podcast", "url": "https://feeds.feedburner.com/sans-isc-podcast", "type": "podcast", "limit": 2},
    ],
    "Space": [
        {"name": "SpaceNews", "url": "https://spacenews.com/feed/"},
    ],
    "Renewables": [
        {"name": "CleanTechnica", "url": "https://cleantechnica.com/feed/"},
        {"name": "Volts", "url": "https://www.volts.wtf/feed"},
    ],
    "Energy": [
        {"name": "Carbon Brief", "url": "https://www.carbonbrief.org/feed/"},
        {"name": "Energy-Storage.news", "url": "https://www.energy-storage.news/feed/"},
    ],
    "MedTech": [
        {"name": "MedTech Dive", "url": "https://www.medtechdive.com/feeds/news/"},
    ],
    "Biotech": [
        {"name": "STAT", "url": "https://www.statnews.com/feed/"},
        {"name": "Fierce Biotech", "url": "https://www.fiercebiotech.com/rss/xml"},
    ],
    "Telecommunications": [
        {"name": "Light Reading", "url": "https://www.lightreading.com/rss.xml"},
        {"name": "arXiv cs.NI", "url": "https://rss.arxiv.org/rss/cs.NI", "type": "paper", "weight": 0.5, "limit": 2},
    ],
    "Robotics": [
        # The previous config pointed at theroboticsreport.com, which looks like a typo
        # for therobotreport.com and would explain the empty Robotics section.
        {"name": "The Robot Report", "url": "https://www.therobotreport.com/feed/"},
        {"name": "IEEE Spectrum Robotics", "url": "https://spectrum.ieee.org/feeds/topic/robotics.rss"},
        {"name": "arXiv cs.RO", "url": "https://rss.arxiv.org/rss/cs.RO", "type": "paper", "weight": 0.5, "limit": 2},
    ],
    "Policy": [
        {"name": "Tech Policy Press", "url": "https://techpolicy.press/feed/"},
        {"name": "EFF Deeplinks", "url": "https://www.eff.org/rss/updates.xml"},
    ],
    "Funding & M&A": [
        {"name": "TechCrunch Venture", "url": "https://techcrunch.com/category/venture/feed/"},
        {"name": "Crunchbase News", "url": "https://news.crunchbase.com/feed/"},
    ],
    "Developer Tools": [
        {"name": "GitHub Blog", "url": "https://github.blog/feed/"},
        {"name": "InfoQ", "url": "https://www.infoq.com/feed/"},
        {"name": "Stack Overflow Blog", "url": "https://stackoverflow.blog/feed/"},
    ],
    # Cross-sector breaking-news sources. Items from these are classified into the
    # sector below only as a holding area; they also feed Top Stories and the
    # emerging-terms detector.
    "Breaking": [
        {"name": "Techmeme", "url": "https://www.techmeme.com/feed.xml", "type": "community", "weight": 0.9, "limit": 6},
        {"name": "Hacker News", "url": "https://hnrss.org/frontpage?points=150", "type": "community", "weight": 0.8, "limit": 6},
    ],
}
