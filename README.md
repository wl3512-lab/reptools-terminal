> ## 🎨 Prototype: Terminal
> 
> This is one of **6 design-direction prototypes** of RepTools. Same Flask app and
> features in every prototype — only the visual identity differs. This one: **Green-on-black CRT/hacker aesthetic: all-monospace, boxy panels, phosphor glow, blinking cursor wordmark.**
> 
> The entire look is driven by `static/css/brand.css` (design tokens + `.cc-*` components).
> Sibling prototypes: cargo-cult · midnight-neon · swiss-light · terminal · soft-glass · editorial-luxe.

# RepTools — Web Application 🚀

A sleek, modern web application for the rep community featuring:
- 📦 **Multi-source package tracking** with human-readable explanations
- 📸 **QC photo scraper** for all major shopping agents
- 🔍 **Reverse image search** across Taobao, Weidian, and 1688

![RepTools Screenshot](screenshot.png)

## Features

### 📦 Package Tracker
- Auto-detects carrier from tracking number format
- Aggregates data from multiple tracking services
- Provides plain-English explanations of shipping statuses
- Beautiful timeline view of tracking history
- Supports all major shipping lines: KR-EMS, GD-EMS, PD-EMS, SAL, DHL, FedEx, UPS, etc.

### 📸 QC Photo Scraper
Automatically extracts quality check photos from:
- ✅ KakoBuy
- ✅ Sugargoo
- ✅ CSSBuy
- ✅ CNFans
- ✅ Joyabuy
- ✅ Pandabuy
- ✅ WeGoBuy
- ✅ Superbuy
- ✅ Hagobuy

### 🔍 Reverse Image Search
- Upload an image or paste a URL
- Searches across Taobao, Weidian, and 1688
- Results sorted by sales volume
- Direct links to product pages

---

## Quick Start

### Option 1: Run Locally

```bash
# Clone the repository
git clone https://github.com/yourusername/reptools.git
cd reptools

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the app
python app.py
```

Open http://localhost:5000 in your browser.

### Option 2: Docker

```bash
# Build the image
docker build -t reptools .

# Run the container
docker run -p 5000:5000 reptools
```

### Option 3: Deploy to Cloud

#### Vercel / Netlify (Frontend Only)
The frontend can be deployed as a static site, but you'll need a separate backend.

#### Railway / Render / Fly.io (Full Stack)
```bash
# Railway
railway login
railway init
railway up

# Render
# Connect your GitHub repo and deploy

# Fly.io
fly launch
fly deploy
```

#### Heroku
```bash
heroku create reptools-app
git push heroku main
```

---

## Configuration

### Environment Variables

Create a `.env` file:

```env
# Flask
FLASK_ENV=production
SECRET_KEY=your-secret-key

# Tracking APIs (get free keys from these services)
TRACK_17TRACK_API_KEY=your-key
TRACK_TRACKINGMORE_API_KEY=your-key
TRACK_AFTERSHIP_API_KEY=your-key

# Image Search (optional)
SERPAPI_KEY=your-key
```

### API Keys

For full functionality, you'll need API keys from tracking services:

| Service | Free Tier | Link |
|---------|-----------|------|
| 17track | 100/day | [api.17track.net](https://api.17track.net/) |
| TrackingMore | 200/month | [trackingmore.com](https://www.trackingmore.com/) |
| AfterShip | 50/month | [aftership.com](https://www.aftership.com/) |
| SerpApi | 100/month | [serpapi.com](https://serpapi.com/) |

---

## Project Structure

```
reptools/
├── app.py                 # Flask backend with all API logic
├── templates/
│   └── index.html         # Single-page frontend
├── static/                # Static assets (if needed)
├── requirements.txt       # Python dependencies
├── Dockerfile             # Container configuration
├── .env.example           # Environment template
└── README.md              # This file
```

---

## API Endpoints

### `POST /api/track`
Track a package.

**Request:**
```json
{
  "tracking_number": "EX123456789CN"
}
```

**Response:**
```json
{
  "tracking_number": "EX123456789CN",
  "carrier": "ems",
  "status": "In transit",
  "explanation": "Your package is on its way...",
  "history": [...]
}
```

### `POST /api/qc`
Scrape QC photos from an agent URL.

**Request:**
```json
{
  "url": "https://www.kakobuy.com/item/..."
}
```

**Response:**
```json
{
  "agent": "KakoBuy",
  "photos": ["url1", "url2", ...],
  "product_name": "...",
  "price": "¥350"
}
```

### `POST /api/search`
Reverse image search.

**Request:**
```json
{
  "image_url": "https://..."
}
```

**Response:**
```json
{
  "products": [
    {
      "title": "...",
      "price": "189",
      "sales": "50000+",
      "platform": "weidian",
      "url": "..."
    }
  ]
}
```

---

## Customization

### Theming
Edit the CSS variables in `templates/index.html`:

```css
:root {
    --bg-primary: #0a0a0b;
    --accent-primary: #22d3ee;
    --accent-secondary: #a855f7;
    /* ... */
}
```

### Adding Agents
Add new agent patterns in `app.py`:

```python
AGENT_PATTERNS = {
    "newagent": [r"newagent\.com"],
    # ...
}
```

---

## Troubleshooting

### "No tracking information found"
- Wait 24-48 hours after shipping for the first scan
- Verify the tracking number is correct
- Some carriers take longer to update their systems

### "No QC photos found"
- Ensure you're using the correct product URL (not a search page)
- The product may not have QC photos uploaded yet
- Try refreshing the agent page first

### CORS Errors
If running frontend separately, ensure Flask-CORS is configured:
```python
CORS(app, origins=["http://localhost:3000"])
```

---

## Contributing

Pull requests welcome! Ideas for improvement:
- Add more tracking providers
- Support additional shopping agents
- Implement caching for faster responses
- Add user accounts for saved tracking
- Build mobile apps (React Native / Flutter)

---

## Disclaimer

This tool is for personal use only. Please respect the terms of service of all platforms and APIs. The developers are not responsible for any misuse.

---

## License

MIT License - feel free to use and modify.

---

Made with ❤️ for the rep community
