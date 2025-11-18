# Background Removal Tool

A full-stack web application for removing backgrounds from images using AI. Built with React + Vite frontend and FastAPI backend.

## Features

- 🖼️ Upload images and automatically remove backgrounds
- 🎨 Choose background color: Transparent, White, or Black
- 📁 Select output format: PNG or JPEG
- 👁️ Side-by-side comparison of original and processed images
- 📥 Download processed images
- 🎯 Checkerboard pattern visualization for transparent backgrounds

## Tech Stack

### Frontend
- React 18
- Vite
- Modern CSS with animations

### Backend
- FastAPI
- rembg (AI-powered background removal)
- Pillow (Image processing)
- Uvicorn (ASGI server)

## Local Development

### Prerequisites
- Node.js 18+
- Python 3.12+
- npm or yarn

### Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Frontend will run on `http://localhost:5173`

### Backend Setup

```bash
cd backend
pip install -r requirements.txt
python main.py
```

Backend will run on `http://localhost:8000`

## Deployment

See [DEPLOYMENT.md](./DEPLOYMENT.md) for detailed deployment instructions to IONOS server using CI/CD pipeline.

### Quick Deploy Steps

1. Set up GitHub Secrets (see DEPLOYMENT.md)
2. Push to `main` branch
3. GitHub Actions will automatically deploy to IONOS server

## Project Structure

```
.
├── frontend/          # React + Vite frontend
│   ├── src/
│   │   ├── App.jsx   # Main React component
│   │   ├── App.css   # Styles
│   │   └── config/
│   │       └── api.js # API configuration
│   └── package.json
├── backend/           # FastAPI backend
│   ├── main.py       # API server
│   └── requirements.txt
├── .github/
│   └── workflows/
│       └── deploy.yml # CI/CD pipeline
├── deploy.sh         # Deployment script
└── nginx.conf.example # Nginx configuration
```

## API Endpoints

- `POST /api/upload` - Upload and process image
- `GET /api/download?imageId=<id>&fileType=<format>` - Download processed image
- `GET /api/health` - Health check

## License

MIT

