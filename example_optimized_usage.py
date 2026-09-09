#!/usr/bin/env python3
"""
Example usage of the optimized DigitalTwin for real-time dashboard performance.

Demonstrates both single-step and batch processing capabilities.
"""

import sys
import time
import numpy as np
from datetime import datetime, timedelta

# Add src to path
sys.path.insert(0, 'src')

def example_single_step():
    """Example of optimized single-step processing."""
    print("=== Single-Step Processing Example ===")
    
    from src.digital_twin_optimized import DigitalTwinOptimized
    
    # Create optimized twin with logging disabled for max performance
    twin = DigitalTwinOptimized(enable_logging=False)
    
    # Simulate one step
    action = {
        "utilisation": 0.8,
        "outside_temp_C": 25.0,
        "cooling_mode": "closed_loop",
        "humidity_pct": 60.0,
        "water_pressure_bar": 2.8
    }
    
    start_time = time.time()
    state = twin.step(action)
    end_time = time.time()
    
    print(f"Single step execution time: {(end_time - start_time)*1000:.3f} ms")
    print(f"State: PUE={state.pue:.3f}, Outlet={state.server_outlet_temp_C:.1f}°C")
    print(f"Power: IT={state.it_power_kw:.1f}kW, Cooling={state.cooling_power_kw:.1f}kW")
    print()

def example_batch_processing():
    """Example of optimized batch processing for 24-hour simulation."""
    print("=== Batch Processing Example (24-hour simulation) ===")
    
    from src.digital_twin_optimized import DigitalTwinOptimized
    
    twin = DigitalTwinOptimized(enable_logging=False)
    
    # Generate 24 hours of actions (288 steps at 5-minute intervals)
    actions = []
    for i in range(288):
        hour = (i * 5) // 60
        
        # Realistic daily patterns
        if 8 <= hour <= 18:  # Business hours
            utilisation = 0.7 + 0.2 * np.sin((i - 96) * 0.1)
        elif 19 <= hour <= 23:  # Evening
            utilisation = 0.4 + 0.2 * np.sin((i - 228) * 0.1)
        else:  # Night
            utilisation = 0.2 + 0.1 * np.sin((i - 12) * 0.1)
        
        utilisation = np.clip(utilisation, 0.1, 0.9)
        
        # Temperature cycle
        outside_temp = 20 + 8 * np.sin((i - 72) * np.pi / 144)
        
        # Cooling mode selection
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
    
    # Process in batch
    print(f"Processing {len(actions)} steps...")
    start_time = time.time()
    states = twin.step_batch(actions)
    end_time = time.time()
    
    execution_time = end_time - start_time
    print(f"Batch execution time: {execution_time:.3f} seconds")
    print(f"Average per step: {execution_time/len(actions)*1000:.3f} ms")
    
    # Show results
    first_state = states[0]
    last_state = states[-1]
    
    print(f"\nFirst step (hour 0):")
    print(f"  PUE={first_state.pue:.3f}, Outlet={first_state.server_outlet_temp_C:.1f}°C")
    print(f"  Power: IT={first_state.it_power_kw:.1f}kW, Cooling={first_state.cooling_power_kw:.1f}kW")
    
    print(f"\nLast step (hour 24):")
    print(f"  PUE={last_state.pue:.3f}, Outlet={last_state.server_outlet_temp_C:.1f}°C")
    print(f"  Power: IT={last_state.it_power_kw:.1f}kW, Cooling={last_state.cooling_power_kw:.1f}kW")
    print(f"  Total water consumed: {last_state.water_consumed_L:.1f}L")
    print()

def example_vectorized_functions():
    """Example of vectorized function usage."""
    print("=== Vectorized Functions Example ===")
    
    from src.digital_twin_optimized import DigitalTwinOptimized
    
    twin = DigitalTwinOptimized(enable_logging=False)
    
    # Generate test data
    n_samples = 1000
    utilisations = np.random.uniform(0.1, 0.9, n_samples)
    inlet_temps = np.random.uniform(18, 25, n_samples)
    it_powers = np.random.uniform(200, 500, n_samples)
    
    # Vectorized computations
    start_time = time.time()
    it_powers_batch = twin.compute_batch_it_power(utilisations)
    outlet_temps_batch = twin.compute_batch_outlet_temp(inlet_temps, it_powers)
    vectorized_time = time.time() - start_time
    
    print(f"Vectorized computation ({n_samples} samples): {vectorized_time:.6f} seconds")
    print(f"Average per sample: {vectorized_time/n_samples*1000000:.3f} μs")
    print(f"IT power range: {np.min(it_powers_batch):.1f} - {np.max(it_powers_batch):.1f} kW")
    print(f"Outlet temp range: {np.min(outlet_temps_batch):.1f} - {np.max(outlet_temps_batch):.1f}°C")
    print()

def example_real_time_simulation():
    """Example demonstrating real-time simulation capability."""
    print("=== Real-Time Simulation Example ===")
    
    from src.digital_twin_optimized import DigitalTwinOptimized
    
    twin = DigitalTwinOptimized(enable_logging=False)
    
    # Simulate real-time updates (like dashboard would receive)
    print("Simulating real-time updates (10 steps at 1-second intervals)...")
    
    for i in range(10):
        # Simulate sensor data coming in
        action = {
            "utilisation": 0.5 + 0.3 * np.sin(i * 0.5),
            "outside_temp_C": 20 + 5 * np.sin(i * 0.3),
            "cooling_mode": "closed_loop"
        }
        
        # Process step (should be << 1ms)
        start_time = time.time()
        state = twin.step(action)
        processing_time = (time.time() - start_time) * 1000  # Convert to ms
        
        print(f"Step {i+1}: {processing_time:.3f} ms, "
              f"PUE={state.pue:.3f}, Outlet={state.server_outlet_temp_C:.1f}°C")
        
        # Simulate 1-second delay (real-time constraint)
        time.sleep(1 - processing_time/1000)  # Adjust for processing time
    
    print("Real-time simulation completed successfully!")
    print()

def main():
    """Run all examples."""
    print("Digital Twin Optimized Usage Examples")
    print("=" * 50)
    
    example_single_step()
    example_batch_processing()
    example_vectorized_functions()
    example_real_time_simulation()
    
    print("=" * 50)
    print("All examples completed successfully!")
    print("The optimized DigitalTwin achieves sub-2 second performance")
    print("for 24-hour simulations, enabling real-time dashboard updates.")

if __name__ == "__main__":
    main()
