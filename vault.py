import os
from config import OLD_ROOT, NEW_ROOT

def get_file(node):
    root = node.get("ROOT_DIR_ON_SERVER")
    name = node.get("FILE_NAME")

    if not root or not name:
        return None

    if root.startswith(OLD_ROOT):
        root = root.replace(OLD_ROOT, NEW_ROOT)

    path = os.path.join(root, name)

    if not os.path.exists(path):
        print("❌ Missing:", path)
        return None
    #print("\n========== VAULT DEBUG ==========")
    #print("FILE_NAME:", name)  
    #print("FULL PATH:", path)  
    #print("EXISTS:", os.path.exists(path))
    #print("=================================\n")
    return path