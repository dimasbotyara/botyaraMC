"""Палитры: Catppuccin Mocha/Latte, Gruvbox, Ayu (Mirage), Monokai."""

THEMES = {
    "Catppuccin Mocha": dict(
        mode="dark", bg="#1e1e2e", panel="#181825", surface="#313244", surface_hover="#45475a",
        border="#45475a", text="#cdd6f4", subtext="#a6adc8", accent="#cba6f7",
        accent_hover="#b4befe", on_accent="#1e1e2e", success="#a6e3a1", danger="#f38ba8"),
    "Catppuccin Latte": dict(
        mode="light", bg="#eff1f5", panel="#e6e9ef", surface="#ccd0da", surface_hover="#bcc0cc",
        border="#acb0be", text="#4c4f69", subtext="#6c6f85", accent="#8839ef",
        accent_hover="#7287fd", on_accent="#eff1f5", success="#40a02b", danger="#d20f39"),
    "Gruvbox": dict(
        mode="dark", bg="#282828", panel="#1d2021", surface="#3c3836", surface_hover="#504945",
        border="#665c54", text="#ebdbb2", subtext="#a89984", accent="#fabd2f",
        accent_hover="#fe8019", on_accent="#282828", success="#b8bb26", danger="#fb4934"),
    "Ayu": dict(
        mode="dark", bg="#1f2430", panel="#191e2a", surface="#2a3141", surface_hover="#343d50",
        border="#3d475c", text="#cccac2", subtext="#8a9199", accent="#ffcc66",
        accent_hover="#ffd580", on_accent="#1f2430", success="#d5ff80", danger="#f28779"),
    "Monokai": dict(
        mode="dark", bg="#272822", panel="#1e1f1c", surface="#3e3d32", surface_hover="#49483e",
        border="#75715e", text="#f8f8f2", subtext="#a59f85", accent="#a6e22e",
        accent_hover="#66d9ef", on_accent="#272822", success="#a6e22e", danger="#f92672"),
}

THEME_NAMES = list(THEMES)
DEFAULT = "Catppuccin Mocha"
