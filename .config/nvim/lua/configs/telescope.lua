require("telescope").setup({
    defaults = {
        file_ignore_patterns = {
            "node_modules",
            ".cache"
        }
    }
})

local opts = { noremap = true }
local opts_desc = function(desc)
    return {
        noremap = true,
        desc = desc,
    }
end

local keymap = vim.api.nvim_set_keymap

keymap('n', '<leader>ff', '<cmd>Telescope find_files hidden=true<cr>', opts)
keymap('n', '<leader>fb', '<cmd>Telescope buffers<cr>', opts)
