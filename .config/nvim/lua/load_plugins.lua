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
