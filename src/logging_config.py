"""
Centralized logging configuration for the Digital Twin system.
"""
import logging
import os
from logging.handlers import RotatingFileHandler
import traceback


def setup_logging():
    """Setup logging configuration for all modules."""
    # Create logs directory if it doesn't exist
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
    os.makedirs(log_dir, exist_ok=True)
    
    # Set up logging configuration
    log_file = os.path.join(log_dir, 'digital_twin.log')
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Set up root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # File handler with rotation
    file_handler = RotatingFileHandler(
        log_file, 
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)
    
    # Add handlers to root logger
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    return root_logger


def log_function_entry(func_name, **kwargs):
    """Log function entry with parameters."""
    logger = logging.getLogger(func_name.split('.')[0] if '.' in func_name else func_name)
    params_str = ', '.join([f"{k}={v}" for k, v in kwargs.items()])
    logger.info(f"ENTER: {func_name}({params_str})")


def log_function_exit(func_name, result=None):
    """Log function exit with result."""
    logger = logging.getLogger(func_name.split('.')[0] if '.' in func_name else func_name)
    if result is not None:
        logger.info(f"EXIT: {func_name} -> Result: {result}")
    else:
        logger.info(f"EXIT: {func_name}")


def log_error(func_name, error, include_traceback=True):
    """Log error with optional stack trace."""
    logger = logging.getLogger(func_name.split('.')[0] if '.' in func_name else func_name)
    error_msg = f"ERROR in {func_name}: {str(error)}"
    
    if include_traceback:
        error_msg += f"\nStack Trace:\n{traceback.format_exc()}"
    
    logger.error(error_msg)


def log_training_progress(model_name, epoch, loss, accuracy=None, **metrics):
    """Log ML model training progress."""
    logger = logging.getLogger(model_name)
    progress_msg = f"TRAINING PROGRESS - {model_name}: Epoch {epoch}, Loss: {loss:.4f}"
    
    if accuracy is not None:
        progress_msg += f", Accuracy: {accuracy:.4f}"
    
    for metric_name, metric_value in metrics.items():
        progress_msg += f", {metric_name}: {metric_value:.4f}"
    
    logger.info(progress_msg)


def log_simulation_step(step_number, **results):
    """Log simulation step results."""
    logger = logging.getLogger('simulation')
    results_str = ', '.join([f"{k}={v}" for k, v in results.items()])
    logger.info(f"SIMULATION STEP {step_number}: {results_str}")


# Initialize logging when module is imported
setup_logging()
