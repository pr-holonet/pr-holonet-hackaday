'use strict';

const _ = require('lodash');
const https = require('https');
const querystring = require('querystring');
const twilio = require('twilio');

const ROCKBLOCK_USERNAME = process.env.ROCKBLOCK_USERNAME;
const ROCKBLOCK_PASSWORD = process.env.ROCKBLOCK_PASSWORD;

const TWILIO_SID = process.env.TWILIO_ACCOUNT_SID;
const TWILIO_TOKEN = process.env.TWILIO_AUTH_TOKEN;
const TWILIO_PHONE = process.env.TWILIO_PHONE_NUMBER;

const ROCKBLOCK_HOST = 'core.rock7.com';
const ROCKBLOCK_MT_ENDPOINT = '/rockblock/MT';

const emeiToNumber = require('./emeiToNumber.json')
const numberToEmei = _.invert(emeiToNumber)


exports.handler = (ev, context, callback) => {
    //console.log(ev, context);

    if (ev.headers['User-Agent'].startsWith('TwilioProxy')) {
        handleFromTwilio(ev, context, callback);
    }
    else {
        handleFromIridium(ev, context, callback);
    }
};

function handleFromTwilio(ev, context, callback) {
    const params = querystring.decode(ev.body);

    if (!validateTwilioSignature(ev, params)) {
        plaintextResponse(callback, '403', 'Bad signature');
        return;
    }

    const from = params['From'];
    const to = params['To'];
    const body = params['Body'];

    const destImei = numberToEmei[to];
    if (!destImei) {
        plaintextResponse(callback, '200', `Error: ${to} is not registered.`);
        return;
    }

    const data = a2hex(`${from}:${body}`);

    const post_params = {
        'imei': destImei,
        'username': ROCKBLOCK_USERNAME,
        'password': ROCKBLOCK_PASSWORD,
        'data': data,
    };
    const post_data = querystring.encode(post_params);

    const empty_resp = new twilio.twiml.MessagingResponse().toString();

    let req = https.request({
        host: ROCKBLOCK_HOST,
        path: ROCKBLOCK_MT_ENDPOINT,
        method: 'POST',
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Content-Length': post_data.length,
        }
    }, res => {
        var body = '';
        res.on('data', function(chunk)  {
            body += chunk;
        });
        res.on('end', function() {
            //console.log('Success response from RockBLOCK: ' + body);
            xmlResponse(callback, '200', empty_resp);
        });
        res.on('error', function(err) {
            console.log('Error response from RockBLOCK: ', err);
            xmlResponse(callback, '500', empty_resp);
        });
    });
    req.on('error', function(err) {
        console.log('Error sending request to RockBLOCK: ', err);
        xmlResponse(callback, '500', empty_resp);
    });
    req.write(post_data);
    req.end();
}

function validateTwilioSignature(ev, params) {
    const headers = ev.headers;
    const host = headers.Host;
    const reqPath = ev.requestContext.path;
    const twilioSignature = headers['X-Twilio-Signature'];
    const url = `https://${host}${reqPath}`;
    const result = twilio.validateRequest(TWILIO_TOKEN, twilioSignature, url,
                                          params);
    if (!result) {
        console.log("Twilio signature validation failed!", url, params,
                    twilioSignature);
    }
    return result;
}

function handleFromIridium(ev, context, callback) {
    const p = querystring.decode(ev.body);
    const emei = p.emei;
    const from = emeiToNumber[emei];

    if (!from) {
        plaintextResponse(callback, '403', 'Not registered');
        return;
    }

    const data = p.data;
    const parsedData = hex2a(data);
    const [num, content] = splitWithTail(parsedData, ':', 1);

    const client = new twilio.Twilio(TWILIO_SID, TWILIO_TOKEN);
    client.messages.create({
        from: TWILIO_PHONE,
        to: num,
        body: content,
    }, function(err, result) {
        if (err) {
            console.log('Error response from Twilio: ', err);
            plaintextResponse(callback, '500', 'not ok');
        }
        else {
            plaintextResponse(callback, '200', 'ok');
        }
    });
}


function hex2a(hex) {
    return new Buffer(hex, 'hex').toString();
}

function a2hex(a) {
    return new Buffer(a, 'ascii').toString('hex');
}

function splitWithTail(str, delim, count) {
    const parts = str.split(delim);
    const tail = parts.slice(count).join(delim);
    let result = parts.slice(0, count);
    result.push(tail);
    return result;
}

function plaintextResponse(callback, statusCode, body) {
    sendResponse(callback, statusCode, 'text/plain', body)
}

function xmlResponse(callback, statusCode, body) {
    sendResponse(callback, statusCode, 'text/xml', body)
}

function sendResponse(callback, statusCode, contentType, body) {
    callback(null, {
        statusCode: statusCode,
        body: body,
        headers: {
            'Content-Type': contentType,
        },
    });
}
