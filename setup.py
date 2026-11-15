from pathlib import Path

from setuptools import setup


ROOT = Path(__file__).resolve().parent


setup(
    name="VencordAutoRepair",
    version="0.4.0",
    description="Repair Vencord automatically after Discord updates",
    long_description=(ROOT / "README.md").read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    license="MIT",
    python_requires=">=3.11",
    py_modules=["app", "app_runtime", "gui", "main", "startup_manager"],
    install_requires=[
        "psutil==7.0.0",
        "requests==2.34.2",
        'pywin32==311; sys_platform == "win32"',
    ],
    entry_points={"gui_scripts": ["VencordAutoRepair=app:main"]},
)
