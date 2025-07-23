import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';

const Layout = ({ children }) => {
  const { user, logout, isAuthenticated, isStaff } = useAuth();
  const [searchQuery, setSearchQuery] = useState('');
  const navigate = useNavigate();

  const handleSearch = (e) => {
    e.preventDefault();
    if (searchQuery.trim()) {
      navigate(`/compounds/search?q=${encodeURIComponent(searchQuery)}`);
    }
  };

  const handleLogout = () => {
    logout();
    navigate('/');
  };

  return (
    <div className="min-vh-100" style={{ backgroundColor: '#1a1a1a' }}>
      {/* Navigation */}
      <nav className="navbar navbar-expand-lg bg-neurobin-dark px-3 py-2">
        <div className="container-fluid">
          <Link className="navbar-brand fw-bold text-light" to="/">
            Neurobin
          </Link>
          
          {/* Mobile toggle button */}
          <button 
            className="navbar-toggler border-0" 
            type="button" 
            data-bs-toggle="collapse" 
            data-bs-target="#navbarContent" 
            aria-controls="navbarContent" 
            aria-expanded="false" 
            aria-label="Toggle navigation"
          >
            <span className="navbar-toggler-icon" style={{ filter: 'invert(1)' }}></span>
          </button>
          
          <div className="collapse navbar-collapse" id="navbarContent">
            {/* Desktop layout */}
            <div className="w-100 d-lg-flex d-none justify-content-end align-items-center">
              <div className="btn-group" role="group">
                {/* Search form */}
                <form onSubmit={handleSearch} className="d-flex my-2 my-lg-0" style={{ margin: 0 }}>
                  <div className="input-group">
                    <input 
                      type="text" 
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      placeholder="Search compounds..." 
                      className="btn-outline-secondary form-control text-light" 
                      style={{ 
                        borderTopRightRadius: 0, 
                        borderBottomRightRadius: 0,
                        backgroundColor: 'transparent',
                        borderColor: '#6c757d'
                      }}
                    />
                    <button 
                      className="btn btn-outline-secondary" 
                      type="submit" 
                      style={{ 
                        borderTopLeftRadius: 0, 
                        borderBottomLeftRadius: 0, 
                        borderTopRightRadius: 0, 
                        borderBottomRightRadius: 0, 
                        borderLeft: 0 
                      }}
                    >
                      <i className="fas fa-search"></i>
                    </button>
                  </div>
                </form>
                
                {/* Options dropdown */}
                <div className="dropdown">
                  <button 
                    className="btn btn-outline-secondary dropdown-toggle" 
                    style={{
                      color: '#FFF', 
                      border: '1px solid #6c757d', 
                      background: 'transparent', 
                      borderTopLeftRadius: 0, 
                      borderBottomLeftRadius: 0, 
                      borderLeft: 0
                    }} 
                    type="button" 
                    data-bs-toggle="dropdown" 
                    aria-expanded="false"
                  >
                    Options
                  </button>
                  <ul className="dropdown-menu dropdown-menu-dark dropdown-menu-end">
                    {/* Primary Links Section */}
                    <li><h6 className="dropdown-header text-white fw-bold">Quick Links</h6></li>
                    <li><Link className="dropdown-item ps-4" to="/compounds">Browse Compounds</Link></li>
                    <li><Link className="dropdown-item ps-4" to="/research">Browse Research</Link></li>
                    {isAuthenticated && (
                      <li><Link className="dropdown-item ps-4" to="/research/add">Add Research</Link></li>
                    )}

                    {isStaff && (
                      <>
                        {/* Admin Section */}
                        <li><hr className="dropdown-divider" /></li>
                        <li><h6 className="dropdown-header text-white fw-bold">Admin</h6></li>
                        <li><Link className="dropdown-item ps-4" to="/compounds/add">Add Compounds</Link></li>
                        <li><Link className="dropdown-item ps-4" to="/mechanisms/add">Add Mechanisms</Link></li>
                        <li><Link className="dropdown-item ps-4" to="/research">Research Review</Link></li>
                      </>
                    )}
                    
                    {/* Profile Section */}
                    <li><hr className="dropdown-divider" /></li>
                    <li><h6 className="dropdown-header text-white fw-bold">Profile</h6></li>
                    {isAuthenticated ? (
                      <>
                        <li>
                          <Link className="dropdown-item ps-4" to="/accounts/profile">
                            <i className="fas fa-user me-2"></i>Profile Dashboard
                          </Link>
                        </li>
                        <li>
                          <button className="dropdown-item ps-4" onClick={handleLogout}>
                            <i className="fas fa-sign-out-alt me-2"></i>Logout
                          </button>
                        </li>
                      </>
                    ) : (
                      <li>
                        <Link className="dropdown-item ps-4" to="/accounts/login">
                          <i className="fas fa-sign-in-alt me-2"></i>Login
                        </Link>
                      </li>
                    )}
                  </ul>
                </div>
              </div>
            </div>
            
            {/* Mobile layout */}
            <div className="d-lg-none w-100 mobile-nav-content">
              {/* Search form full width */}
              <form onSubmit={handleSearch} className="mb-3">
                <div className="input-group">
                  <input 
                    type="text" 
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Search compounds..." 
                    className="form-control bg-dark text-light" 
                    style={{ border: '1px solid #6c757d' }}
                  />
                  <button className="btn btn-outline-secondary" type="submit">
                    <i className="fas fa-search"></i>
                  </button>
                </div>
              </form>
              
              {/* Mobile navigation links */}
              <div className="list-group list-group-flush">
                <Link className="list-group-item list-group-item-action bg-dark text-light border-secondary" to="/compounds">
                  Browse Compounds
                </Link>
                <Link className="list-group-item list-group-item-action bg-dark text-light border-secondary" to="/research">
                  Browse Research
                </Link>
                {isAuthenticated && (
                  <Link className="list-group-item list-group-item-action bg-dark text-light border-secondary" to="/research/add">
                    Add Research
                  </Link>
                )}
                {isStaff && (
                  <>
                    <div className="text-light px-3 py-2 fw-bold">Admin</div>
                    <Link className="list-group-item list-group-item-action bg-dark text-light border-secondary ps-4" to="/compounds/add">
                      Add Compounds
                    </Link>
                    <Link className="list-group-item list-group-item-action bg-dark text-light border-secondary ps-4" to="/mechanisms/add">
                      Add Mechanisms
                    </Link>
                  </>
                )}
                <div className="text-light px-3 py-2 fw-bold">Profile</div>
                {isAuthenticated ? (
                  <>
                    <Link className="list-group-item list-group-item-action bg-dark text-light border-secondary ps-4" to="/accounts/profile">
                      <i className="fas fa-user me-2"></i>Profile Dashboard
                    </Link>
                    <button className="list-group-item list-group-item-action bg-dark text-light border-secondary ps-4" onClick={handleLogout}>
                      <i className="fas fa-sign-out-alt me-2"></i>Logout
                    </button>
                  </>
                ) : (
                  <Link className="list-group-item list-group-item-action bg-dark text-light border-secondary ps-4" to="/accounts/login">
                    <i className="fas fa-sign-in-alt me-2"></i>Login
                  </Link>
                )}
              </div>
            </div>
          </div>
        </div>
      </nav>

      {/* Main content */}
      <main style={{ paddingTop: '20px', minHeight: 'calc(100vh - 76px)' }}>
        {children}
      </main>
    </div>
  );
};

export default Layout;
