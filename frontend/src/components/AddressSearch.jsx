import { useState } from 'react';
import { Autocomplete } from '@react-google-maps/api';

function AddressSearch({ mapRef, onPlaceSelected }) {
  const [autocomplete, setAutocomplete] = useState(null);
  const [searchValue, setSearchValue] = useState('');

  const onLoad = (autocompleteInstance) => {
    setAutocomplete(autocompleteInstance);
  };

  const onPlaceChanged = () => {
    if (autocomplete !== null) {
      const place = autocomplete.getPlace();
      
      if (place.geometry && place.geometry.location) {
        const location = {
          lat: place.geometry.location.lat(),
          lng: place.geometry.location.lng(),
        };
        
        const address = place.formatted_address || place.name || '';
        
        // Pan and zoom to location
        if (mapRef && mapRef.current) {
          mapRef.current.panTo(location);
          mapRef.current.setZoom(19);
        }
        
        // Notify parent
        if (onPlaceSelected) {
          onPlaceSelected(location, address);
        }
        
        setSearchValue(address);
      }
    }
  };

  return (
    <div className="address-search">
      <Autocomplete
        onLoad={onLoad}
        onPlaceChanged={onPlaceChanged}
      >
        <input
          type="text"
          placeholder="Search for an address..."
          value={searchValue}
          onChange={(e) => setSearchValue(e.target.value)}
          className="search-input"
        />
      </Autocomplete>
    </div>
  );
}

export default AddressSearch;

