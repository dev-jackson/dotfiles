local status, telescope = pcall(require, "telescope")

if not status then return end

local actions = require("telescope.actions")

local function telescope_buffer_dir()
    return vim.fn.expand("%:p:h")
end

local fb_actions = require 'telescope'.extensions.file_browser.actions

telescope.setup({
    defaults = {
        mappings = {
            n = {
                ['q'] = actions.close
            }
        },
        file_ignore_patterns = {
            "node_modules",
            ".cache"
        }
    },
    extensions = {
        file_browser = {
            theme = "dropdown"
        },
        hijack_netrw = true,
        mappings = {
            ['i'] = {
                ['<C-w>'] = function()
                    vim.cmd('normal vbd')
                end
            },
            ['n'] = {
                ['N'] = fb_actions.create,
                ['h'] = fb_actions.goto_parent_dir,
                ['/'] = function()
                    vim.cmd('startinsert')
                end
            }
        }
    }
})

telescope.load_extension('file_browser')

local opts = { noremap = true, silent = true }
-- local opts_desc = function(desc)
--     return {
--         noremap = true,
--         desc = desc,
--     }
-- end

local keymap = vim.api.nvim_set_keymap

keymap('n', ';f', '<cmd>Telescope find_files hidden=true<cr>', opts)
keymap('n', ';r', '<cmd>lua require("telescope.builtin").live_grep()<cr>', opts)
keymap('n', '\\\\', '<cmd>Telescope buffers<cr>', opts)
keymap('n', ';t', 'lua require("telescope.builtin").help_tags()<cr>', opts)
keymap('n', ';;', 'lua require("telescope.builtin").resume()<cr>', opts)
keymap('n', ';e', 'lua require("telescope.builtin").diagnostics()<cr>', opts)
