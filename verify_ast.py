import ast
with open('/Users/isakzvegelj/clawd/villa-adora-work/app.py') as f:
    tree = ast.parse(f.read())
funcs = [n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
print(f"Functions ({len(funcs)}): {funcs}")
print("AST parse: OK")
