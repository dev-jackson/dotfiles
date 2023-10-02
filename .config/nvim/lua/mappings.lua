local opts = { noremap = true }
local opts_desc = function(desc)
    return {
        noremap = true,
        desc = desc,
    }
end

local keymap = vim.api.nvim_set_keymap


keymap('n', '<C-s>', '<cmd>:w<cr>', opts)
