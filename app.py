import tkinter as tk

from runtime.app_runtime import AIAssistantApp


def main() -> None:
    root_window = tk.Tk()
    AIAssistantApp(root_window)
    root_window.mainloop()


if __name__ == '__main__':
    main()
