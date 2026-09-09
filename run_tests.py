#!/usr/bin/env python3
"""
Simple test runner for the digital twin test suite.
Runs tests without pytest dependency issues.
"""

import sys
import os
import traceback
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def run_test_module(module_name, test_class_name):
    """Run all tests in a specific test module."""
    print(f"\n{'='*60}")
    print(f"Running {module_name}")
    print(f"{'='*60}")
    
    try:
        # Import the test module
        test_module = __import__(f'tests.{module_name}', fromlist=[test_class_name])
        test_class = getattr(test_module, test_class_name)
        
        # Create instance
        test_instance = test_class()
        
        # Get all test methods
        test_methods = [method for method in dir(test_instance) if method.startswith('test_')]
        
        passed = 0
        failed = 0
        
        for test_method in test_methods:
            try:
                print(f"  {test_method}... ", end='')
                
                # Run setup if available
                if hasattr(test_instance, 'setup_method'):
                    test_instance.setup_method()
                
                # Run the test
                getattr(test_instance, test_method)()
                
                print("✓ PASSED")
                passed += 1
                
            except Exception as e:
                print(f"✗ FAILED")
                print(f"    Error: {str(e)}")
                failed += 1
                if '--tb' in sys.argv:
                    traceback.print_exc()
        
        print(f"\nResults: {passed} passed, {failed} failed")
        return failed == 0
        
    except Exception as e:
        print(f"Failed to run {module_name}: {str(e)}")
        traceback.print_exc()
        return False

def main():
    """Main test runner."""
    print("Digital Twin Test Suite")
    print("=" * 60)
    
    # Test modules to run
    test_modules = [
        ('test_digital_twin', 'TestDigitalTwin'),
        ('test_data_pipeline', 'TestDataPipeline'),
        ('test_anomaly_detector', 'TestAnomalyDetector')
    ]
    
    all_passed = True
    
    for module_name, test_class_name in test_modules:
        try:
            module_passed = run_test_module(module_name, test_class_name)
            all_passed = all_passed and module_passed
        except Exception as e:
            print(f"Error running {module_name}: {e}")
            all_passed = False
    
    print(f"\n{'='*60}")
    if all_passed:
        print("🎉 All tests passed!")
        return 0
    else:
        print("❌ Some tests failed!")
        return 1

if __name__ == "__main__":
    sys.exit(main())
