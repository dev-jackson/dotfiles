require("telescope").setup()

local opts = { noremap = true }
local opts_desc = function(desc)
    return {
        noremap = true,
        desc = desc,
    }
end

local keymap = vim.api.nvim_set_keymap

keymap('n', '<leader>ff', '<cmd>Telescope find_files hidden=true<cr>', opts)
