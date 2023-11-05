
function update_form(data) {
	$('#brightness').val(data.brightness)
	$('#clockFormatString').val(data.clockFormatString)
}

function send_change(changes) {
	var qp = "?"
	var keys = Object.keys(changes)
	for (var x = 0; x < keys.length; ++x) {
		qp = qp + keys[x] + '=' + changes[keys[x]]
		if (x != keys.length - 1) {
			qp = qp + '&'
		}
	}

	$.get('/api/config' + qp, update_form)
}

$(function () {

	$.get('/api/config', update_form)

})