from cx_Freeze import Executable, setup


setup(
    name="VencordAutoRepair",
    version="0.4.0",
    description="Repair Vencord automatically after Discord updates",
    options={
        "build_exe": {
            "include_files": [("assets", "assets")],
        },
    },
    executables=[
        Executable("main.py", target_name="main.exe"),
        Executable("startup_manager.py", target_name="startup_manager.exe"),
    ],
)
