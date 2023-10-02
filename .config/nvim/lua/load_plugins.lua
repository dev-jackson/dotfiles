local plugins = {
    { "williamboman/mason.nvim" },
    { "williamboman/mason-lspconfig.nvim"
    },
    { "neovim/nvim-lspconfig" },
    { "neovim/nvim-lspconfig" },

    -- Files
    {
        'nvim-telescope/telescope.nvim',
        branch = '0.1.x',
        dependencies = { 'nvim-lua/plenary.nvim' }
    },

    { "nvim-treesitter/nvim-treesitter", build = ":TSUpdate" },

    { 'neovim/nvim-lspconfig' },
    { 'hrsh7th/cmp-nvim-lsp' },
    { 'hrsh7th/cmp-buffer' },
    { 'hrsh7th/cmp-path' },
    { 'hrsh7th/cmp-cmdline' },
    { 'hrsh7th/nvim-cmp' },
    { 'hrsh7th/cmp-vsnip' },
    { 'hrsh7th/vim-vsnip' },

    { "windwp/nvim-autopairs" },
    { "vim-airline/vim-airline" },

    -- Files views
    {
        "nvim-neo-tree/neo-tree.nvim",
        branch = "v3.x",
        dependencies = {
            "nvim-lua/plenary.nvim",
            "nvim-tree/nvim-web-devicons", -- not strictly required, but recommended
            "MunifTanjim/nui.nvim",
            {
                's1n7ax/nvim-window-picker',
                version = '2.*',
                config = function()
                    require 'window-picker'.setup({
                        filter_rules = {
                            include_current_win = false,
                            autoselect_one = true,
                            -- filter using buffer options
                            bo = {
                                -- if the file type is one of following, the window will be ignored
                                filetype = { 'neo-tree', "neo-tree-popup", "notify" },
                                -- if the buffer type is one of following, the window will be ignored
                                buftype = { 'terminal', "quickfix" },
                            },
                        },
                    })
                end,
            },
        }
    },
    -- Themes
    {
        "folke/tokyonight.nvim",
        lazy = false,
        priority = 1000,
        opts = {},
    }
}


require('lazy').setup(plugins, {
})
