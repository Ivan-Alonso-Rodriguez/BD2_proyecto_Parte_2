/** Google Maps oficial; Leaflet conserva el mapa sin clave. */
let googleLoading;

function productContent(title, price) {
  const content=document.createElement('div');
  const heading=document.createElement('strong');heading.textContent=title;
  const detail=document.createElement('p');detail.textContent=price;
  content.append(heading,detail);
  return content;
}

function loadGoogleMaps(scriptUrl, status) {
  if (window.google?.maps?.Map) return Promise.resolve(window.google.maps);
  if (!googleLoading) {
    googleLoading=new Promise((resolve,reject)=>{
      const script=document.createElement('script');
      const callback='__atlasGoogleMapsReady';
      const url=new URL(scriptUrl);
      url.searchParams.set('callback',callback);
      let pending=true;
      const fail=message=>{
        status(message);
        if (!pending) return;
        pending=false;
        clearTimeout(timer);
        script.remove();
        reject(Error(message));
      };
      const timer=setTimeout(()=>fail('Google Maps no respondió. Revisa tu conexión e inténtalo de nuevo.'),20000);
      window[callback]=()=>{
        if (!pending) return;
        if (!window.google?.maps?.Map) {fail('Google Maps no pudo inicializarse.');return;}
        pending=false;
        clearTimeout(timer);
        status('');
        resolve(window.google.maps);
      };
      window.gm_authFailure=()=>fail('Google Maps rechazó la clave. Revisa Maps JavaScript API, la facturación y los sitios permitidos en Google Cloud.');
      script.async=true;
      script.src=url.href;
      script.onerror=()=>fail('No se pudo descargar Google Maps. Revisa tu conexión a internet.');
      document.head.append(script);
    }).catch(exception=>{googleLoading=null;throw exception;});
  }
  return googleLoading;
}

export async function createStoreMap(element, config, center, onCenterChange, status) {
  const money=new Intl.NumberFormat('es-PE',{style:'currency',currency:'PEN'});
  if (config.provider==='google') {
    const maps=await loadGoogleMaps(config.script_url,status);
    const map=new maps.Map(element,{center:{lat:center[0],lng:center[1]},zoom:12,mapTypeControl:false,streetViewControl:false});
    const info=new maps.InfoWindow();
    let radiusCircle, fitted=false;
    map.data.setStyle({icon:{path:maps.SymbolPath.CIRCLE,scale:7,strokeColor:'#fff',strokeWeight:2,fillColor:'#7760bc',fillOpacity:.9}});
    map.addListener('click',event=>{
      if (event.latLng) onCenterChange([event.latLng.lat(),event.latLng.lng()]);
    });
    map.data.addListener('click',event=>{
      info.setContent(productContent(event.feature.getProperty('title'),event.feature.getProperty('price')));
      info.setPosition(event.latLng);
      info.open({map,shouldFocus:false});
    });
    const clear=()=>{
      info.close();
      map.data.forEach(feature=>map.data.remove(feature));
      if (radiusCircle) {radiusCircle.setMap(null);radiusCircle=null;}
    };
    return {
      clear,
      render(rows, currentCenter, radius) {
        clear();
        maps.event.trigger(map,'resize');
        map.data.addGeoJson({type:'FeatureCollection',features:rows.map(row=>({
          type:'Feature',id:row.id,geometry:{type:'Point',coordinates:[row.lon,row.lat]},
          properties:{title:row.titulo,price:money.format(row.precio)},
        }))});
        if (!fitted && rows.length) {
          const bounds=new maps.LatLngBounds();
          for (const row of rows) bounds.extend({lat:row.lat,lng:row.lon});
          map.fitBounds(bounds,24);
          fitted=true;
        }
        if (radius!==null) radiusCircle=new maps.Circle({map,center:{lat:currentCenter[0],lng:currentCenter[1]},radius,strokeColor:'#8872be',strokeOpacity:.8,strokeWeight:1,fillColor:'#8872be',fillOpacity:.07,clickable:false});
      },
    };
  }

  if (!window.L) throw Error('No se cargó Leaflet. Revisa los archivos frontend/vendor.');
  const map=L.map(element,{preferCanvas:true}).setView(center,12);
  const layers=L.layerGroup().addTo(map);
  let radiusCircle, fitted=false;
  const tiles=L.tileLayer(config.tile_url,{attribution:config.attribution,maxZoom:config.max_zoom});
  tiles.on('tileerror',()=>status('No se pudo cargar el mapa. Revisa tu conexión a internet.'));
  tiles.on('tileload',()=>status(''));
  tiles.addTo(map);
  map.on('click',event=>onCenterChange([event.latlng.lat,event.latlng.lng]));
  const clear=()=>{
    layers.clearLayers();
    if (radiusCircle) {map.removeLayer(radiusCircle);radiusCircle=null;}
  };
  return {
    clear,
    render(rows,currentCenter,radius) {
      map.invalidateSize();
      clear();
      for (const row of rows) {
        L.circleMarker([row.lat,row.lon],{radius:rows.length>1000?3:7,color:'#fff',weight:rows.length>1000?1:2,fillColor:'#7760bc',fillOpacity:.9})
          .bindPopup(()=>productContent(row.titulo,money.format(row.precio))).addTo(layers);
      }
      if (!fitted && rows.length) {
        map.fitBounds(rows.map(row=>[row.lat,row.lon]),{padding:[24,24],maxZoom:12});
        fitted=true;
      }
      if (radius!==null) radiusCircle=L.circle(currentCenter,{radius,color:'#8872be',fillOpacity:.07,weight:1,dashArray:'5 5'}).addTo(map);
    },
  };
}
