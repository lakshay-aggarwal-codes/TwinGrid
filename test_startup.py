#!/usr/bin/env python3
"""
Test script to verify the API can start without database dependencies.
"""

import os
import sys

# Add current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_import():
    """Test that the API module can be imported."""
    try:
        import api.main
        print("✅ API module imports successfully")
        return True
    except Exception as e:
        print(f"❌ API import failed: {e}")
        return False

def test_fastapi_app():
    """Test that FastAPI app is created."""
    try:
        import api.main
        app = api.main.app
        print(f"✅ FastAPI app created: {app.title}")
        print(f"   Version: {app.version}")
        return True
    except Exception as e:
        print(f"❌ FastAPI app creation failed: {e}")
        return False

def main():
    """Run all tests."""
    print("🚀 Testing Digital Twin API Startup...")
    print("=" * 50)
    
    tests = [
        ("API Import", test_import),
        ("FastAPI App", test_fastapi_app),
    ]
    
    results = []
    for name, test_func in tests:
        print(f"\n📋 Testing {name}...")
        result = test_func()
        results.append((name, result))
    
    print("\n" + "=" * 50)
    print("📊 Test Results:")
    
    all_passed = True
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"   {name}: {status}")
        if not result:
            all_passed = False
    
    if all_passed:
        print("\n🎉 All tests passed! API is ready for deployment.")
        print("\n📝 Startup command:")
        print("   uvicorn api.main:app --host 0.0.0.0 --port $PORT")
    else:
        print("\n⚠️  Some tests failed. Check the errors above.")
    
    return all_passed

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
