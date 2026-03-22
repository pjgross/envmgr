#!/bin/bash

# EnvManager Phase 0 Setup Script
# This script sets up the development environment for EnvManager

set -e

echo "🚀 Setting up EnvManager Development Environment..."
echo ""

# Check prerequisites
echo "📋 Checking prerequisites..."
command -v docker >/dev/null 2>&1 || { echo "❌ Docker is required but not installed. Aborting." >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "❌ Python 3 is required but not installed. Aborting." >&2; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "❌ npm is required but not installed. Aborting." >&2; exit 1; }

echo "✅ Prerequisites check passed"
echo ""

# Start Docker containers
echo "🐳 Starting Docker containers..."
docker-compose up -d

echo "⏳ Waiting for databases to be ready..."
sleep 10

echo "✅ Docker containers started"
echo ""

# Setup backend
echo "🐍 Setting up Python backend..."
cd backend

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
echo "Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Run database migrations
echo "Running database migrations..."
alembic revision --autogenerate -m "Initial migration"
alembic upgrade head

# Create a demo tenant and user
echo "Creating demo tenant and user..."
python3 << EOF
import asyncio
from app.db.base import AsyncSessionLocal
from app.db.models.user import Tenant, User
from app.core.security import get_password_hash

async def create_demo_data():
    async with AsyncSessionLocal() as session:
        # Create demo tenant
        tenant = Tenant(name="Demo Organization", slug="demo")
        session.add(tenant)
        await session.flush()
        
        # Create admin user
        admin_user = User(
            tenant_id=tenant.id,
            username="admin",
            email="admin@demo.com",
            password_hash=get_password_hash("admin123"),
            role="Admin",
            notification_preferences={"email": True, "slack": False, "teams": False}
        )
        session.add(admin_user)
        await session.commit()
        
        print(f"✅ Created demo tenant: {tenant.slug}")
        print(f"✅ Created admin user: {admin_user.username}")
        print(f"   Login credentials:")
        print(f"   - Tenant: demo")
        print(f"   - Username: admin")
        print(f"   - Password: admin123")

asyncio.run(create_demo_data())
EOF

cd ..
echo "✅ Backend setup complete"
echo ""

# Setup frontend
echo "⚛️  Setting up React frontend..."
cd frontend

# Install dependencies
echo "Installing npm dependencies..."
npm install

cd ..
echo "✅ Frontend setup complete"
echo ""

echo "🎉 Setup complete!"
echo ""
echo "📝 Next steps:"
echo "1. Start the backend:"
echo "   cd backend && source venv/bin/activate && uvicorn app.main:app --reload"
echo ""
echo "2. In a new terminal, start the frontend:"
echo "   cd frontend && npm run dev"
echo ""
echo "3. Open your browser to http://localhost:5173"
echo ""
echo "4. Login with:"
echo "   - Tenant: demo"
echo "   - Username: admin"
echo "   - Password: admin123"
echo ""
echo "📚 API Documentation: http://localhost:8000/docs"
echo ""
