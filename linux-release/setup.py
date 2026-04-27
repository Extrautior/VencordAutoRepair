from cx_Freeze import Executable, setup


setup(
    name="VencordAutoRepair",
    version="0.2.0",
    description="Repair Vencord automatically after Discord updates",
    executables=[
        Executable("main.py", target_name="main.exe"),
        Executable("startup_manager.py", target_name="startup_manager.exe"),
    ],
)
