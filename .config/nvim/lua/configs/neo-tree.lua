require("neo-tree").setup({
    close_if_last_windows = false,
    poup_border_style = "rounded",
    enable_git_status = true,
    enable_diagnostics = true,
    enable_normal_mode_for_inputs = false,
})

local keymap = vim.api.nvim_set_keymap


keymap("n", "<leader>e", "<CMD>Neotree toggle<CR>", {})
