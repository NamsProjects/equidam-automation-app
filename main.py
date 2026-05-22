"""
main.py
Entry point for the Equidam Projections Uploader app
"""

import logging
from gui.gui_main import launch_app


if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,  # Change to logging.DEBUG for verbose output
        format='%(levelname)s: %(message)s'
    )
    
    # Start the GUI
    launch_app()