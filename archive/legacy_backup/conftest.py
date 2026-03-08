import sys
import os

# Get the absolute path of the current directory
root_path = os.path.abspath(os.path.dirname(__file__))

# Map the hyphenated folder to a name Python can import
sys.path.insert(0, root_path)

# This is the "Magic" trick: 
# We manually inject the hyphenated folder into the system modules 
# under the name with an underscore.
try:
    import tradingview_webhook_bot
except ImportError:
    # If the folder has a hyphen, we manually load it
    import importlib.util
    folder_path = os.path.join(root_path, "tradingview_webhook_bot")
    spec = importlib.util.spec_from_file_location("tradingview_webhook_bot", os.path.join(folder_path, "__init__.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules["tradingview_webhook_bot"] = module
    spec.loader.exec_module(module)
