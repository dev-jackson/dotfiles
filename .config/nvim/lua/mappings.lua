local function map(mode, lhs, rhs)
    vim.keymap.set(mode, lhs, rhs, { silent = true })
end


map('n', '<C-s>', '<cmd>:w<cr>')

-- Toggleterm
map('n', '<leader>tf', '<cmd>ToggleTerm direction=float<cr>')
map('n', '<leader>tt', '<cmd>ToggleTerm direction=tab<cr>')

-- Buffer
map('n', '<TAB>', '<cmd>bnext<cr>')
map('n', '<S-TAB>', '<cmd>bprevious<cr>')

-- Window
map('n', '<leader>;', '<cmd>vsplit<cr>')
map('n', '<leader>p', '<cmd>split<cr>')

-- Window Navigation
map("n", "<C-h>", "<C-w>h")
map("n", "<C-l>", "<C-w>l")
map("n", "<C-k>", "<C-w>k")
map("n", "<C-j>", "<C-w>j")

-- Resize Windows
map("n", "<C-Left>", "<C-w><")
map("n", "<C-Right>", "<C-w>>")
map("n", "<C-Up>", "<C-w>+")
map("n", "<C-Down>", "<C-w>-")
