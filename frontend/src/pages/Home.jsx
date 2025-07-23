import React from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

const Home = () => {
  const { isAuthenticated } = useAuth();

  return (
    <div className="d-flex flex-column align-items-center justify-content-center" style={{ minHeight: '60vh' }}>
      <div className="text-center">
        <h1 className="fw-bold mb-3" style={{ color: '#FFF' }}>
          Research, Track<br />Stay Safe
        </h1>
        <p className="lead text-secondary mb-4" style={{ maxWidth: '400px', margin: '0 auto' }}>
          Discover, document, and share compound research. Neurobin helps you track mechanisms, targets, and safety — all in one place.
        </p>
        <div className="d-flex flex-column flex-sm-row justify-content-center gap-3 mt-4">
          <Link 
            to="/compounds" 
            className="btn btn-lg px-4" 
            style={{ 
              background: '#FFF', 
              color: '#111', 
              border: 'none' 
            }}
          >
            Browse Compounds
          </Link>
          {isAuthenticated && (
            <Link 
              to="/logs/intake" 
              className="btn btn-lg px-4" 
              style={{ 
                background: 'transparent', 
                color: '#FFF', 
                border: '1px solid #FFF' 
              }}
            >
              Log Compound
            </Link>
          )}
        </div>
      </div>
    </div>
  );
};

export default Home;
