"""PyInstaller entry point: thin wrapper so the chronos package's
relative imports resolve correctly when frozen."""
from chronos.main import main

if __name__ == "__main__":
    main()
