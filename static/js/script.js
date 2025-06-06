let addresses = [];

function addAddress() {
    const addressInput = document.getElementById('address');
    const savedAddressSelect = document.getElementById('saved-addresses');
    const address = addressInput.value.trim() || savedAddressSelect.value;
    if (address) {
        addresses.push(address);
        const li = document.createElement('li');
        li.textContent = address;
        document.getElementById('address-list').appendChild(li);
        addressInput.value = '';
        savedAddressSelect.value = '';
    } else {
        alert('Please enter or select a valid address.');
    }
}

function optimizeRoute() {
    if (addresses.length < 2) {
        alert('Please enter at least two addresses.');
        return;
    }

    fetch('/optimize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ addresses })
    })
    .then(response => response.json())
    .then(data => {
        if (data.error) {
            alert(data.error);
            return;
        }
        const resultDiv = document.getElementById('result');
        resultDiv.innerHTML = `
            <h2>Optimized Route</h2>
            <p><strong>Distance:</strong> ${data.summary.distance}</p>
            <h3>Route Order:</h3>
            <ul>${data.summary.order.map(addr => `<li>${addr}</li>`).join('')}</ul>
        `;
        document.getElementById('map').innerHTML = data.map_html;
    })
    .catch(error => {
        alert('Error optimizing route: ' + error);
    });
}
