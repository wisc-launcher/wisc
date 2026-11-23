"""Build script for wisc-skin-bridge.jar companion Java agent.
Compiles the agent with Java 8 bytecode compatibility (--release 8) and bundles
ASM shaded into a private package (wisc.skinbridge.asm) so Fabric Loader's
Knot classpath validator never throws duplicate ASM class exceptions.
"""

import argparse
import os
import shutil
import struct
import subprocess
import zipfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR / "src"
BUILD_DIR = BASE_DIR / "build"
CLASSES_DIR = BUILD_DIR / "classes"
OUTPUT_JAR = BASE_DIR / "wisc-skin-bridge.jar"

# Look for asm jar in .minecraft libraries
APPDATA = os.environ.get("APPDATA", "")
MC_LIBRARIES = Path(APPDATA) / ".minecraft" / "libraries"


def find_asm_jar() -> Path | None:
    candidates = list(MC_LIBRARIES.glob("**/asm-[0-9]*.jar"))
    # Filter out asm-tree, asm-analysis, etc.
    valid = [
        p for p in candidates
        if p.name.startswith("asm-") and not any(x in p.name for x in ("tree", "analysis", "commons", "util", "all"))
    ]
    if valid:
        return sorted(valid, key=lambda p: p.stat().st_mtime, reverse=True)[0]
    return None


def find_javac() -> str:
    javac = shutil.which("javac")
    if javac:
        return javac
    for jdk in Path("C:/Program Files/Java").glob("jdk*"):
        candidate = jdk / "bin" / "javac.exe"
        if candidate.is_file():
            return str(candidate)
    raise RuntimeError("Could not find javac executable.")


def find_jar() -> str:
    jar = shutil.which("jar")
    if jar:
        return jar
    for jdk in Path("C:/Program Files/Java").glob("jdk*"):
        candidate = jdk / "bin" / "jar.exe"
        if candidate.is_file():
            return str(candidate)
    raise RuntimeError("Could not find jar executable.")


def relocate_class(data: bytes, old_pkg: bytes, new_pkg: bytes) -> bytes:
    """Relocates package references in a Java .class file constant pool."""
    if not data.startswith(b"\xCA\xFE\xBA\xBE"):
        return data
    magic, minor, major, cp_count = struct.unpack(">IHHH", data[:10])
    pos = 10
    new_cp = bytearray()
    i = 1
    while i < cp_count:
        tag = data[pos]
        pos += 1
        if tag == 1:  # CONSTANT_Utf8
            length = struct.unpack(">H", data[pos:pos + 2])[0]
            pos += 2
            val = data[pos:pos + length]
            pos += length
            if old_pkg in val:
                val = val.replace(old_pkg, new_pkg)
            new_cp.append(1)
            new_cp.extend(struct.pack(">H", len(val)))
            new_cp.extend(val)
        elif tag in (3, 4):  # Integer, Float
            new_cp.append(tag)
            new_cp.extend(data[pos:pos + 4])
            pos += 4
        elif tag in (5, 6):  # Long, Double (occupies 2 CP indices)
            new_cp.append(tag)
            new_cp.extend(data[pos:pos + 8])
            pos += 8
            i += 1
        elif tag in (7, 8, 16, 19, 20):  # Class, String, MethodType, Module, Package
            new_cp.append(tag)
            new_cp.extend(data[pos:pos + 2])
            pos += 2
        elif tag in (9, 10, 11, 12, 17, 18):  # Ref, NameAndType, Dynamic, InvokeDynamic
            new_cp.append(tag)
            new_cp.extend(data[pos:pos + 4])
            pos += 4
        elif tag == 15:  # MethodHandle
            new_cp.append(tag)
            new_cp.extend(data[pos:pos + 3])
            pos += 3
        else:
            raise ValueError(f"Unknown constant pool tag: {tag}")
        i += 1

    rest = data[pos:]
    return data[:8] + struct.pack(">H", cp_count) + bytes(new_cp) + rest


def build(install_dir: Path | None = None) -> Path:
    print("[WiscSkinBridge Build] Starting build...")
    asm_jar = find_asm_jar()
    if asm_jar is None and OUTPUT_JAR.is_file():
        with zipfile.ZipFile(OUTPUT_JAR) as bundled:
            if "wisc/skinbridge/asm/ClassReader.class" in bundled.namelist():
                asm_jar = OUTPUT_JAR
    if not asm_jar:
        raise RuntimeError("Could not find ASM in Minecraft libraries or the bundled bridge.")
    print(f"[WiscSkinBridge Build] Using ASM from: {asm_jar}")

    javac = find_javac()
    jar_tool = find_jar()

    # Clean build dirs
    if BUILD_DIR.resolve() != BUILD_DIR or not BUILD_DIR.is_relative_to(BASE_DIR):
        raise RuntimeError("Bridge build output must stay inside its source directory.")
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    CLASSES_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Extract and relocate ASM classes into wisc/skinbridge/asm/
    print("[WiscSkinBridge Build] Unpacking & shading ASM to wisc/skinbridge/asm/...")
    old_pkg = b"org/objectweb/asm"
    new_pkg = b"wisc/skinbridge/asm"
    with zipfile.ZipFile(asm_jar, "r") as z:
        for member in z.infolist():
            if member.filename.startswith("org/objectweb/asm/") and member.filename.endswith(".class"):
                raw_bytes = z.read(member)
                relocated = relocate_class(raw_bytes, old_pkg, new_pkg)
                rel_path = member.filename.replace("org/objectweb/asm", "wisc/skinbridge/asm")
                target_file = CLASSES_DIR / rel_path
                target_file.parent.mkdir(parents=True, exist_ok=True)
                target_file.write_bytes(relocated)
            elif member.filename.startswith("wisc/skinbridge/asm/") and member.filename.endswith(".class"):
                target_file = CLASSES_DIR / member.filename
                target_file.parent.mkdir(parents=True, exist_ok=True)
                target_file.write_bytes(z.read(member))

    # 2. Compile SkinBridge sources with --release 8
    print("[WiscSkinBridge Build] Compiling Java sources (--release 8)...")
    sources = list(SRC_DIR.glob("**/*.java"))
    compile_cmd = [
        javac,
        "--release", "8",
        "-cp", str(CLASSES_DIR),
        "-d", str(CLASSES_DIR),
    ] + [str(s) for s in sources]
    res = subprocess.run(compile_cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"Compilation error:\n{res.stderr}\n{res.stdout}")
        raise RuntimeError(f"javac failed with code {res.returncode}")

    # 3. Create Manifest
    manifest_path = BUILD_DIR / "MANIFEST.MF"
    manifest_content = (
        "Manifest-Version: 1.0\n"
        "Premain-Class: wisc.skinbridge.SkinBridgeAgent\n"
        "Can-Redefine-Classes: true\n"
        "Can-Retransform-Classes: true\n"
        "\n"
    )
    manifest_path.write_bytes(manifest_content.encode("utf-8"))

    # 4. Package jar
    print(f"[WiscSkinBridge Build] Packaging {OUTPUT_JAR}...")
    jar_cmd = [
        jar_tool,
        "cfm",
        str(OUTPUT_JAR),
        str(manifest_path),
        "-C", str(CLASSES_DIR),
        "."
    ]
    res = subprocess.run(jar_cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"jar packaging error:\n{res.stderr}\n{res.stdout}")
        raise RuntimeError(f"jar failed with code {res.returncode}")

    # Building alone leaves installed game data untouched.
    if install_dir is not None:
        install_dir.mkdir(parents=True, exist_ok=True)
        target = install_dir / OUTPUT_JAR.name
        shutil.copy2(OUTPUT_JAR, target)
        return target
    print(f"[WiscSkinBridge Build] Built: {OUTPUT_JAR} ({OUTPUT_JAR.stat().st_size} bytes)")
    return OUTPUT_JAR


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-dir", type=Path, help="Also copy the built agent to this tools directory")
    build(parser.parse_args().install_dir)
