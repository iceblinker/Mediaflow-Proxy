function userViewLink(reCaptchaResponse) {
    $.post(endpoint, {id: linkId, reCaptchaResponse: reCaptchaResponse, ref: getReferrer()}, function (data) {
        if (data.status === 'error') {
            if (typeof data.code !== 'undefined' && data.code === 429) {
                grecaptcha.render('colReCaptcha', reCaptchaConfig);
                $('#colLoading').addClass('d-none');
                $('#colReCaptcha').removeClass('d-none');
                return false;
            }
            alert(data.message);
            return false;
        }

        var link = data.data.value;
        window.location.href = link;

    }, 'json').fail(function(xhr, status, error) {
        $('#colLoading').html('<div class="alert alert-danger" role="alert">Unexpected Error!</div>');
        console.log(xhr);
        console.log(status);
        console.log(error);
    });
}

function getReferrer() {
    return (document.referrer === window.location.href ? false : document.referrer);
}

function userViewPlayer(reCaptchaResponse) {
    $.post(endpoint, {id: linkId, reCaptchaResponse: reCaptchaResponse, ref: getReferrer()}, function (data) {
        if (data.status === 'error') {
            if (typeof data.code !== 'undefined' && data.code === 429) {
                grecaptcha.render('captchaContainer', reCaptchaConfig);
                $('#loadingPlayer').addClass('d-none');
                $('#loadCaptcha').removeClass('d-none');
                return false;
            }
            alert(data.message);
            return false;
        }
        
        window[loadPlayer](data.data);

    }, 'json');
}
    
$(document).ready(function () {
    if (typeof adl !== "undefined" && typeof adsLoaded === "undefined") {
        $('.displayNoAds').removeClass('d-none');
        $('.hideNoAds').addClass('d-none');
    }

    if (typeof noContextMenu !== "undefined" && noContextMenu) {
        $('body').contextmenu(function () {
            return false;
        });
    }

});

$(document).ready(function () {

    $('#fakePlayer').click(function () {
        $(this).addClass('d-none');
        $('#loadingPlayer').removeClass('d-none');
        userViewPlayer();
    });
        
    $('.btnClickToContinueLink').click(function () {
        $('#colFilename').addClass('d-none');
        $('#colButtons').addClass('d-none');
        $('#colLoading').removeClass('d-none');
        userViewLink();
    });

    $('#reportLink.btn').click(function () {

        $(this).prop('disabled', true);
        $('#openModelLinkReportConfirm').prop('disabled', true);

        var msgbox = $('#modelLinkReportConfirm .modal-body p');
        $(msgbox).html('<div class="text-center"><div class="spinner-border" role="status"><span class="sr-only">Loading...</span></div></div>');

        $.post("/ajax/linkReport.php", {id: linkId}, function (data) {
            if (data.status === 'error') {
                $(msgbox).html('<div class="alert alert-danger" role="alert">' + data.message + '</div>');
            } else {
                $(msgbox).html('<div class="alert alert-success" role="alert">Success!</div>');
            }
        }, 'json');

    });

    $('body.embedplayer').hover(function () {
        setTimeout(function () {
            $('.navbar-autohide').animate({top: 0 - $('.navbar-autohide').outerHeight() + 'px'}, 400);
        }, 2000);

    }, function () {
        $('.navbar-autohide').animate({top: '0px'}, 200);
    });
    
    $('body.embedplayer').mousemove(function () {
        $('.navbar-autohide').animate({top: '0px'}, 200);
    });

});