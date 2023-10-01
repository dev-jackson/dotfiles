vim.o.relativenumber = true
vim.o.modelines = 0
vim.o.compatible = false
vim.o.backspace = '2'

vim.o.writebackup = false
vim.o.backup = false

vim.g.skip_defaults_vim = 1

vim.o.exrc = 1

vim.o.number = true
vim.o.autoindent = true
vim.o.softtabstop = 4
vim.o.tabstop = 4
vim.o.expandtab = true
vim.o.shiftwidth = 4
vim.o.showcmd = true
vim.o.ignorecase = true
vim.o.smartcase = true
vim.o.linebreak = true
vim.o.hidden = true
vim.o.laststatus = 3
vim.o.cmdheight = 1

vim.o.clipboard = 'unnamedplus'
vim.o.completeopt = 'menu,menuone,noselect'

-- don't fold any text at startup
vim.o.foldmethod = 'indent'
vim.o.foldlevel = 99
vim.o.foldlevelstart = 99

vim.g.mapleader = ' '
vim.g.maplocalleader = [[  ]]

vim.o.mouse = 'a'
vim.env.NVIM_TUI_ENABLE_TRUE_COLOR = 1
vim.o.termguicolors = true
