"""Fix the sentence-ending regex in tts_engine.py."""
import re

path = "src/tts_engine.py"
with open(path, "r", encoding="utf-8") as f:
    src = f.read()

# The broken line — replace the whole sentence-ending block cleanly
old_block = (
    "    # Collapse multiple spaces / dangling punctuation from stripped markers\n"
    "    text = re.sub(r' {2,}', ' ', text)\n"
    "    text = re.sub(r'[,;]\\s*$', '.', text)      # trailing comma/semicolon → period\n"
    "    text = re.sub(r'(\\w)$', r'.', text)      # add period if ending mid-word\n"
    "    return text.strip()"
)

new_block = (
    "    # Collapse multiple spaces / dangling punctuation from stripped markers\n"
    "    text = re.sub(r' {2,}', ' ', text)\n"
    "    text = re.sub(r'[,;]\\s*$', '.', text)      # trailing comma/semicolon → period\n"
    "    text = re.sub(r'(\\w)$', lambda m: m.group(1) + '.', text)  # add period if no ending punctuation\n"
    "    return text.strip()"
)

if old_block in src:
    src = src.replace(old_block, new_block)
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    print("Fixed OK")
else:
    # Find and show context
    idx = src.find("add period if ending")
    print("Block not found exactly. Context:", repr(src[idx-100:idx+100]))
