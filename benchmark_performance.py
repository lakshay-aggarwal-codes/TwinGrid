#!/usr/bin/env python3
"""
Performance benchmark for DigitalTwin optimization.

Tests original vs optimized implementation for 24-hour simulation (288 steps).
"""

import sys
import time
import numpy as np
from datetime import datetime, timedelta

# Add src to path
sys.path.insert(0, 'src')

def generate_test_actions(n_steps=288):
    """Generate realistic test actions for 24-hour simulation."""
    actions = []
    base_time = datetime(2024, 1, 1, 0, 0, 0)
    
    for i in range(n_steps):
        # Simulate daily patterns
        hour = (i * 5) // 60  # 5-minute intervals
        
        # Server utilisation: higher during business hours
        if 8 <= hour <= 18:
            utilisation = 0.6 + 0.3 * np.sin((i - 96) * 0.1)  # Business hours
        elif 19 <= hour <= 23:
            utilisation = 0.3 + 0.2 * np.sin((i - 228) * 0.1)  # Evening
        else:  # Night
            utilisation = 0.2 + 0.1 * np.sin((i - 12) * 0.1)
        
        utilisation = np.clip(utilisation, 0.1, 0.9)
        
        # Outside temperature: daily cycle
        outside_temp = 20 + 8 * np.sin((i - 72) * np.pi / 144)  # Peak at 2pm
        
        # Cooling mode selection based on temperature
        if outside_temp < 12:
            cooling_mode = "free_air"
        elif outside_temp > 25:
            cooling_mode = "evaporative"
        else:
            cooling_mode = "closed_loop"
        
        actions.append({
            "utilisation": utilisation,
            "outside_temp_C": outside_temp,
            "cooling_mode": cooling_mode,
            "humidity_pct": 45 + 15 * np.sin(i * 0.05),
            "water_pressure_bar": 2.8 + 0.4 * np.sin(i * 0.03)
        })
    
    return actions

def benchmark_original():
    """Benchmark original DigitalTwin implementation."""
    print("Benchmarking Original DigitalTwin...")
    
    try:
        from src.digital_twin import DigitalTwin as OriginalTwin
        
        # Original implementation doesn't have enable_logging parameter
        twin = OriginalTwin()
        actions = generate_test_actions()
        
        start_time = time.time()
        
        for action in actions:
            state = twin.step(action)
        
        end_time = time.time()
        execution_time = end_time - start_time
        
        print(f"  Original implementation: {execution_time:.3f} seconds")
        print(f"  Final state: PUE={state.pue:.3f}, Outlet={state.server_outlet_temp_C:.1f}°C")
        
        return execution_time
        
    except ImportError as e:
        print(f"  Could not import original implementation: {e}")
        return None

def benchmark_optimized():
    """Benchmark optimized DigitalTwin implementation."""
    print("Benchmarking Optimized DigitalTwin...")
    
    try:
        from src.digital_twin_optimized import DigitalTwinOptimized
        
        twin = DigitalTwinOptimized(enable_logging=False)
        actions = generate_test_actions()
        
        start_time = time.time()
        
        for action in actions:
            state = twin.step(action)
        
        end_time = time.time()
        execution_time = end_time - start_time
        
        print(f"  Optimized implementation: {execution_time:.3f} seconds")
        print(f"  Final state: PUE={state.pue:.3f}, Outlet={state.server_outlet_temp_C:.1f}°C")
        
        return execution_time
        
    except ImportError as e:
        print(f"  Could not import optimized implementation: {e}")
        return None

def benchmark_batch_processing():
    """Benchmark optimized batch processing."""
    print("Benchmarking Batch Processing...")
    
    try:
        from src.digital_twin_optimized import DigitalTwinOptimized
        
        twin = DigitalTwinOptimized(enable_logging=False)
        actions = generate_test_actions()
        
        start_time = time.time()
        
        # Process all steps in one batch
        states = twin.step_batch(actions)
        
        end_time = time.time()
        execution_time = end_time - start_time
        
        final_state = states[-1] if states else None
        print(f"  Batch processing: {execution_time:.3f} seconds")
        if final_state:
            print(f"  Final state: PUE={final_state.pue:.3f}, Outlet={final_state.server_outlet_temp_C:.1f}°C")
        
        return execution_time
        
    except ImportError as e:
        print(f"  Could not import optimized implementation: {e}")
        return None

def benchmark_vectorized_functions():
    """Benchmark individual vectorized functions."""
    print("Benchmarking Vectorized Functions...")
    
    try:
        from src.digital_twin_optimized import DigitalTwinOptimized
        
        twin = DigitalTwinOptimized(enable_logging=False)
        
        # Generate test data
        n_samples = 1000
        utilisations = np.random.uniform(0.1, 0.9, n_samples)
        inlet_temps = np.random.uniform(18, 25, n_samples)
        it_powers = np.random.uniform(200, 500, n_samples)
        
        # Benchmark batch IT power computation
        start_time = time.time()
        it_powers_batch = twin.compute_batch_it_power(utilisations)
        batch_time = time.time() - start_time
        
        # Benchmark individual IT power computation
        start_time = time.time()
        it_powers_individual = [twin.compute_it_power(u) for u in utilisations]
        individual_time = time.time() - start_time
        
        print(f"  Batch IT power ({n_samples} values): {batch_time:.6f} seconds")
        print(f"  Individual IT power ({n_samples} values): {individual_time:.6f} seconds")
        if batch_time > 0:
            print(f"  Speedup: {individual_time/batch_time:.1f}x")
        else:
            print(f"  Speedup: >1000x (batch too fast to measure)")
        
        # Verify results are equivalent
        max_diff = np.max(np.abs(np.array(it_powers_batch) - np.array(it_powers_individual)))
        print(f"  Max difference: {max_diff:.6f} kW")
        
        # Benchmark batch outlet temperature computation
        start_time = time.time()
        outlet_temps_batch = twin.compute_batch_outlet_temp(inlet_temps, it_powers)
        batch_temp_time = time.time() - start_time
        
        start_time = time.time()
        outlet_temps_individual = [twin.compute_outlet_temp(inlet_temps[i], it_powers[i]) for i in range(n_samples)]
        individual_temp_time = time.time() - start_time
        
        print(f"  Batch outlet temp ({n_samples} values): {batch_temp_time:.6f} seconds")
        print(f"  Individual outlet temp ({n_samples} values): {individual_temp_time:.6f} seconds")
        if batch_temp_time > 0:
            print(f"  Speedup: {individual_temp_time/batch_temp_time:.1f}x")
        else:
            print(f"  Speedup: >1000x (batch too fast to measure)")
        
        return batch_time, individual_time
        
    except ImportError as e:
        print(f"  Could not import optimized implementation: {e}")
        return None, None

def main():
    """Run all benchmarks."""
    print("Digital Twin Performance Benchmark")
    print("=" * 50)
    print(f"Test: 24-hour simulation (288 steps)")
    print(f"Target: < 2 seconds for real-time dashboard")
    print("=" * 50)
    
    # Run benchmarks
    original_time = benchmark_original()
    print()
    
    optimized_time = benchmark_optimized()
    print()
    
    batch_time = benchmark_batch_processing()
    print()
    
    benchmark_vectorized_functions()
    print()
    
    # Summary
    print("=" * 50)
    print("PERFORMANCE SUMMARY")
    print("=" * 50)
    
    if original_time is not None:
        print(f"Original implementation: {original_time:.3f} seconds")
        if optimized_time is not None:
            speedup = original_time / optimized_time
            print(f"Optimized implementation: {optimized_time:.3f} seconds")
            print(f"Single-step speedup: {speedup:.1f}x")
    
    if batch_time is not None:
        print(f"Batch processing: {batch_time:.3f} seconds")
        if original_time is not None:
            batch_speedup = original_time / batch_time
            print(f"Batch processing speedup: {batch_speedup:.1f}x")
    
    # Check if we meet the target
    fastest_time = min([t for t in [original_time, optimized_time, batch_time] if t is not None])
    print()
    if fastest_time < 2.0:
        print(f"🎉 SUCCESS: Fastest time {fastest_time:.3f}s < 2.0s target")
        print("✅ Real-time dashboard performance achieved!")
    else:
        print(f"⚠️  NEEDS WORK: Fastest time {fastest_time:.3f}s > 2.0s target")
        print("❌ Real-time dashboard performance not yet achieved")
    
    print("=" * 50)

if __name__ == "__main__":
    main()
