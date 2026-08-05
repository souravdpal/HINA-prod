const express = require('express');
const fs = require('fs');
const path = require('path');
const bodyParser = require('body-parser');

const app = express();
const PORT = process.env.PORT || 3000;
const DATA_FILE = path.join(__dirname, 'products.json');

app.set('view engine', 'ejs');
app.set('views', path.join(__dirname, 'views'));
app.use(express.static(path.join(__dirname, 'public')));
app.use(bodyParser.urlencoded({ extended: true }));

// Helper functions for JSON database operations
function getProducts() {
  try {
    const data = fs.readFileSync(DATA_FILE, 'utf8');
    return JSON.parse(data);
  } catch (err) {
    return [];
  }
}

function saveProducts(products) {
  fs.writeFileSync(DATA_FILE, JSON.stringify(products, null, 2), 'utf8');
}

// Routes
app.get('/', (req, res) => {
  const products = getProducts();
  const categories = [...new Set(products.map(p => p.category))];
  
  // Filtering & Searching
  let filteredProducts = [...products];
  const { category, search } = req.query;

  if (category) {
    filteredProducts = filteredProducts.filter(p => p.category === category);
  }
  if (search) {
    const query = search.toLowerCase();
    filteredProducts = filteredProducts.filter(p => 
      p.title.toLowerCase().includes(query) || 
      p.description.toLowerCase().includes(query)
    );
  }

  res.render('index', { 
    products: filteredProducts, 
    categories, 
    selectedCategory: category || '', 
    searchQuery: search || '' 
  });
});

app.get('/product/:id', (req, res) => {
  const products = getProducts();
  const product = products.find(p => p.id === req.params.id);
  if (!product) {
    return res.status(404).send('Product Not Found');
  }
  res.render('product', { product });
});

// Admin Dashboard Routes
app.get('/admin', (req, res) => {
  const products = getProducts();
  res.render('admin', { products, error: null, success: null });
});

app.post('/admin/add', (req, res) => {
  const products = getProducts();
  const { title, category, price, imageUrl, affiliateUrl, description, rating, isFeatured } = req.body;

  if (!title || !price || !imageUrl || !affiliateUrl) {
    return res.render('admin', { 
      products, 
      error: 'Please fill out all required fields.', 
      success: null 
    });
  }

  const newProduct = {
    id: Date.now().toString(),
    title,
    category: category || 'General',
    price: parseFloat(price).toFixed(2),
    imageUrl,
    affiliateUrl,
    description: description || '',
    rating: rating || '5.0',
    isFeatured: isFeatured === 'on'
  };

  products.push(newProduct);
  saveProducts(products);

  res.redirect('/admin?success=added');
});

app.get('/admin/delete/:id', (req, res) => {
  let products = getProducts();
  products = products.filter(p => p.id !== req.params.id);
  saveProducts(products);
  res.redirect('/admin?success=deleted');
});

app.listen(PORT, () => {
  console.log(`Amazon Affiliate site running on http://localhost:${PORT}`);
});
