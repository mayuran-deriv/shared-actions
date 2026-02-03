import { useState } from 'react';
import './Weather.css';

function Weather() {
  const [city, setCity] = useState('');
  const [weather, setWeather] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const searchWeather = async () => {
    if (!city.trim()) {
      setError('Please enter a city name');
      return;
    }

    setLoading(true);
    setError('');

    try {
      // Using Open-Meteo API (free, no API key required)
      // First, get coordinates from city name using a geocoding service
      const geoResponse = await fetch(
        `https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(city)}&count=1&language=en&format=json`
      );
      const geoData = await geoResponse.json();

      if (!geoData.results || geoData.results.length === 0) {
        setError('City not found. Please try again.');
        setWeather(null);
        setLoading(false);
        return;
      }

      const { latitude, longitude, name, country } = geoData.results[0];

      // Get weather data
      const weatherResponse = await fetch(
        `https://api.open-meteo.com/v1/forecast?latitude=${latitude}&longitude=${longitude}&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m&timezone=auto`
      );
      const weatherData = await weatherResponse.json();

      setWeather({
        city: `${name}, ${country}`,
        temperature: Math.round(weatherData.current.temperature_2m),
        humidity: weatherData.current.relative_humidity_2m,
        windSpeed: Math.round(weatherData.current.wind_speed_10m),
        weatherCode: weatherData.current.weather_code,
      });
    } catch (err) {
      setError('Failed to fetch weather data. Please try again.');
      setWeather(null);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter') {
      searchWeather();
    }
  };

  const getWeatherDescription = (code) => {
    const weatherCodes = {
      0: '☀️ Clear sky',
      1: '🌤️ Mainly clear',
      2: '⛅ Partly cloudy',
      3: '☁️ Overcast',
      45: '🌫️ Foggy',
      48: '🌫️ Foggy',
      51: '🌦️ Light drizzle',
      53: '🌦️ Moderate drizzle',
      55: '🌧️ Dense drizzle',
      61: '🌧️ Slight rain',
      63: '🌧️ Moderate rain',
      65: '🌧️ Heavy rain',
      71: '🌨️ Slight snow',
      73: '🌨️ Moderate snow',
      75: '❄️ Heavy snow',
      77: '🌨️ Snow grains',
      80: '🌦️ Slight rain showers',
      81: '🌧️ Moderate rain showers',
      82: '⛈️ Violent rain showers',
      85: '🌨️ Slight snow showers',
      86: '❄️ Heavy snow showers',
      95: '⛈️ Thunderstorm',
      96: '⛈️ Thunderstorm with hail',
      99: '⛈️ Thunderstorm with hail',
    };
    return weatherCodes[code] || '🌡️ Weather data';
  };

  return (
    <div className="weather">
      <div className="weather-search">
        <input
          type="text"
          className="weather-input"
          placeholder="Enter city name..."
          value={city}
          onChange={(e) => setCity(e.target.value)}
          onKeyPress={handleKeyPress}
        />
        <button
          className="weather-button"
          onClick={searchWeather}
          disabled={loading}
        >
          {loading ? 'Searching...' : 'Search'}
        </button>
      </div>

      {error && <div className="weather-error">{error}</div>}

      {weather && (
        <div className="weather-result">
          <h2 className="weather-city">{weather.city}</h2>
          <div className="weather-temp">{weather.temperature}°C</div>
          <div className="weather-description">
            {getWeatherDescription(weather.weatherCode)}
          </div>
          <div className="weather-details">
            <div className="weather-detail">
              <span className="detail-label">Humidity</span>
              <span className="detail-value">{weather.humidity}%</span>
            </div>
            <div className="weather-detail">
              <span className="detail-label">Wind Speed</span>
              <span className="detail-value">{weather.windSpeed} km/h</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default Weather;
