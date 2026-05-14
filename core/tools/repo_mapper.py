import os
import ast
import json
import re

class RepoMapper:
    """Tool to aggressively index repos via AST/Regex to preserve LLM context window."""
    
    EXCLUDE_DIRS = {"node_modules", ".git", "__pycache__", "venv", ".venv", "env", "dist", "build", ".next", ".vscode"}
    
    def map_structure(self, workspace_path: str) -> str:
        """Scan directory and return a JSON structure of classes/functions."""
        if not os.path.exists(workspace_path):
            return json.dumps({"error": f"Path {workspace_path} does not exist."})
        if not os.path.isdir(workspace_path):
            return json.dumps({"error": f"Path {workspace_path} is a file, not a directory."})
            
        repo_map = {}
        for root, dirs, files in os.walk(workspace_path):
            # In-place modify dirs array to prune excluded folders
            dirs[:] = [d for d in dirs if d not in self.EXCLUDE_DIRS]
            
            for file in files:
                # Exclude huge JSONs or binaries
                if file.endswith('.json') and file == "package-lock.json": continue
                
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, workspace_path).replace("\\", "/")
                
                if file.endswith('.py'):
                    repo_map[rel_path] = self._parse_python(file_path)
                elif file.endswith('.js') or file.endswith('.ts') or file.endswith('.jsx') or file.endswith('.tsx'):
                    repo_map[rel_path] = self._parse_js_regex(file_path)
                else:
                    repo_map[rel_path] = {"type": "unparsed_file"}
                    
        return json.dumps(repo_map, indent=2)

    def _parse_python(self, filepath: str) -> dict:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            tree = ast.parse(content)
        except Exception as e:
            return {"error": str(e)}
            
        file_map = {"classes": [], "functions": []}
        
        try:
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    cls_info = {
                        "name": node.name,
                        "docstring": ast.get_docstring(node),
                        "methods": []
                    }
                    for subnode in node.body:
                        if isinstance(subnode, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            args = [arg.arg for arg in subnode.args.args]
                            cls_info["methods"].append({
                                "name": subnode.name,
                                "args": args,
                                "docstring": ast.get_docstring(subnode)
                            })
                    file_map["classes"].append(cls_info)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    args = [arg.arg for arg in node.args.args]
                    file_map["functions"].append({
                        "name": node.name,
                        "args": args,
                        "docstring": ast.get_docstring(node)
                    })
        except Exception:
            pass
            
        return file_map

    def _parse_js_regex(self, filepath: str) -> dict:
        # Rugged fallback for JS ecosystem
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                text = f.read()
                
            js_map = {"classes": [], "functions": []}
            class_matches = re.findall(r'class\s+([A-Za-z0-9_]+)', text)
            func_matches = re.findall(r'function\s+([A-Za-z0-9_]+)\s*\(([^)]*)\)', text)
            arrow_funcs = re.findall(r'(const|let|var)\s+([A-Za-z0-9_]+)\s*=\s*\(([^)]*)\)\s*=>', text)
            
            for c in class_matches:
                js_map["classes"].append({"name": c})
            for f in func_matches:
                js_map["functions"].append({"name": f[0], "args": [a.strip() for a in f[1].split(',') if a.strip()]})
            for af in arrow_funcs:
                js_map["functions"].append({"name": af[1], "args": [a.strip() for a in af[2].split(',') if a.strip()]})
                
            return js_map
        except Exception as e:
            return {"error": f"Regex parsing failed: {e}"}
