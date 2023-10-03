require("lualine").setup({
    options = {
        icons_enabled = true,
        always_dividi_middle = true,
        ignore_focues = {},
        globalstatus = false,
        refesh = {
            statusline = 1000,
            tabline = 1000,
            winbar = 1000,
        },
    },
    tabline = {},
    winbar = {},
    inactive_winbar = {},
    extensions = {}
})
